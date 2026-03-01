"""SSHMachine controller -- reconciles SSHMachine resources.

This is the core controller of the provider. It handles:
- Bootstrap via SSH (kubeadm init/join)
- Cleanup via SSH (kubeadm reset)
- Host selection from SSHHost pool (Metal3-style inventory)
- Status management (providerID, addresses, conditions)
"""

import asyncio
import base64
import datetime
import logging
import os
import posixpath
import re
import shlex
import socket
import time

import kopf
import kubernetes
import yaml

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.ssh import SSHClient, SSHResult

logger = logging.getLogger(__name__)

DEFAULT_EXTERNAL_ETCD_CA_FILE = "/etc/kubernetes/pki/etcd-external/ca.crt"
DEFAULT_EXTERNAL_ETCD_CERT_FILE = "/etc/kubernetes/pki/etcd-external/client.crt"
DEFAULT_EXTERNAL_ETCD_KEY_FILE = "/etc/kubernetes/pki/etcd-external/client.key"
SSHMACHINE_RECONCILE_INTERVAL = int(
    os.environ.get("SSHMACHINE_RECONCILE_INTERVAL", os.environ.get("RECONCILE_INTERVAL", "60")),
)
SSHMACHINE_DISTRIBUTED_LOCK_ENABLED = os.environ.get("SSHMACHINE_DISTRIBUTED_LOCK_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
}
SSHMACHINE_DISTRIBUTED_LOCK_TTL_SECONDS = int(os.environ.get("SSHMACHINE_DISTRIBUTED_LOCK_TTL_SECONDS", "7200"))
SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS = int(
    os.environ.get("SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS", "5"),
)
SSHMACHINE_DISTRIBUTED_LOCK_ANNOTATION = "infrastructure.cluster.x-k8s.io/reconcile-lock"
BOOTSTRAP_SUCCESS_SENTINEL_PATH = "/run/cluster-api/bootstrap-success.complete"
BOOTSTRAP_SENTINEL_HIT_OUTPUT = "__CAPI_PROVIDER_SSH_BOOTSTRAP_SENTINEL_HIT__"
KUBELET_READY_SENTINEL_OUTPUT = "__CAPI_PROVIDER_SSH_KUBELET_READY__"
BOOTSTRAP_PHASE_REASON_MAP = {
    "reset": "BootstrapResetFailed",
    "init": "BootstrapInitFailed",
    "join": "BootstrapJoinFailed",
}
BOOTSTRAP_CHECK_STRATEGY_DEFAULT = "ssh"
BOOTSTRAP_CHECK_STRATEGY_SSH = "ssh"
BOOTSTRAP_CHECK_STRATEGY_NONE = "none"
BOOTSTRAP_CHECK_STRATEGIES = {
    BOOTSTRAP_CHECK_STRATEGY_SSH,
    BOOTSTRAP_CHECK_STRATEGY_NONE,
}
BOOTSTRAP_DIAGNOSTIC_MAX_EXCERPT = 240
BOOTSTRAP_DIAGNOSTIC_REDACTIONS = (
    (re.compile(r"(?i)(--token(?:=|\s+))\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(--certificate-key(?:=|\s+))\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(--discovery-token-ca-cert-hash(?:=|\s+))\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(token|certificate-key|discovery-token-ca-cert-hash)\b\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
)
_RECONCILE_LOCKS: dict[str, asyncio.Lock] = {}


def _build_reconcile_lock_holder() -> str:
    """Return a stable lock holder identity across process restarts."""
    raw_holder = os.environ.get("POD_NAME") or os.environ.get("HOSTNAME") or socket.gethostname()
    holder = (raw_holder or "unknown").strip().replace("|", "_")
    return holder or "unknown"


_RECONCILE_LOCK_HOLDER = _build_reconcile_lock_holder()
MACHINE_INFRASTRUCTURE_READY_CONDITION = "InfrastructureReady"
MACHINE_BOOTSTRAP_EXEC_SUCCEEDED_CONDITION = "BootstrapExecSucceeded"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _condition(condition_type: str, status: str, reason: str, message: str) -> dict:
    return {
        "type": condition_type,
        "status": status,
        "lastTransitionTime": _now_iso(),
        "reason": reason,
        "message": message,
    }


def _ready_condition(message: str) -> dict:
    return _condition("Ready", "True", "Provisioned", message)


def _not_ready_condition(reason: str, message: str) -> dict:
    return _condition("Ready", "False", reason, message)


def _info_condition(condition_type: str, reason: str, message: str) -> dict:
    return _condition(condition_type, "True", reason, message)


def _normalize_bootstrap_check_strategy(spec: dict) -> str:
    """Validate and normalize SSHMachine bootstrap check strategy."""
    raw = spec.get("bootstrapCheckStrategy")
    if raw is None:
        return BOOTSTRAP_CHECK_STRATEGY_DEFAULT
    if not isinstance(raw, str):
        raise kopf.PermanentError("spec.bootstrapCheckStrategy must be a string (`ssh` or `none`)")

    strategy = raw.strip().lower()
    if strategy not in BOOTSTRAP_CHECK_STRATEGIES:
        raise kopf.PermanentError("spec.bootstrapCheckStrategy must be one of: ssh, none")
    return strategy


def _machine_lifecycle_conditions(
    *,
    ready: bool,
    ready_reason: str,
    ready_message: str,
    infrastructure_ready: bool,
    infrastructure_reason: str,
    infrastructure_message: str,
    bootstrap_succeeded: bool,
    bootstrap_reason: str,
    bootstrap_message: str,
    extras: list[dict] | None = None,
) -> list[dict]:
    conditions = [
        _condition("Ready", "True" if ready else "False", ready_reason, ready_message),
        _condition(
            MACHINE_INFRASTRUCTURE_READY_CONDITION,
            "True" if infrastructure_ready else "False",
            infrastructure_reason,
            infrastructure_message,
        ),
        _condition(
            MACHINE_BOOTSTRAP_EXEC_SUCCEEDED_CONDITION,
            "True" if bootstrap_succeeded else "False",
            bootstrap_reason,
            bootstrap_message,
        ),
    ]
    if extras:
        conditions.extend(extras)
    return conditions


def _has_machine_owner(owner_references: list[dict] | None) -> bool:
    """Check if the resource has a CAPI Machine owner reference."""
    if not owner_references:
        return False
    return any(
        ref.get("apiVersion", "").startswith("cluster.x-k8s.io/") and ref.get("kind") == "Machine"
        for ref in owner_references
    )


def _get_machine_owner_ref(owner_references: list[dict] | None) -> dict | None:
    """Get the CAPI Machine owner reference."""
    if not owner_references:
        return None
    for ref in owner_references:
        if ref.get("apiVersion", "").startswith("cluster.x-k8s.io/") and ref.get("kind") == "Machine":
            return ref
    return None


async def _read_ssh_key(namespace: str, secret_name: str, secret_key: str = "value") -> str:
    """Read SSH private key from a Kubernetes Secret."""
    api = kubernetes.client.CoreV1Api()
    secret = api.read_namespaced_secret(name=secret_name, namespace=namespace)
    if secret.data is None or secret_key not in secret.data:
        raise kopf.PermanentError(f"Secret {namespace}/{secret_name} missing key '{secret_key}'")
    return base64.b64decode(secret.data[secret_key]).decode("utf-8")


async def _read_bootstrap_data(namespace: str, machine_name: str) -> str | None:
    """Read bootstrap data from the Machine's bootstrap data secret.

    The bootstrap data secret is created by the bootstrap provider (kubeadm)
    and referenced from the Machine resource.
    """
    api = kubernetes.client.CustomObjectsApi()
    try:
        machine = api.get_namespaced_custom_object(
            group="cluster.x-k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="machines",
            name=machine_name,
        )
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return None
        raise

    bootstrap_ref = machine.get("spec", {}).get("bootstrap", {}).get("dataSecretName")
    if not bootstrap_ref:
        return None

    core_api = kubernetes.client.CoreV1Api()
    try:
        secret = core_api.read_namespaced_secret(name=bootstrap_ref, namespace=namespace)
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return None
        raise

    if secret.data is None or "value" not in secret.data:
        return None

    return base64.b64decode(secret.data["value"]).decode("utf-8")


async def _read_secret_value(namespace: str, secret_name: str, secret_key: str = "value") -> str:
    """Read arbitrary secret data as UTF-8 text."""
    api = kubernetes.client.CoreV1Api()
    secret = api.read_namespaced_secret(name=secret_name, namespace=namespace)
    if secret.data is None or secret_key not in secret.data:
        raise kopf.PermanentError(f"Secret {namespace}/{secret_name} missing key '{secret_key}'")
    return base64.b64decode(secret.data[secret_key]).decode("utf-8")


def _required_secret_ref(config: dict, field: str) -> tuple[str, str]:
    """Resolve a required Secret key ref in ``{name,key}`` shape."""
    ref = config.get(field, {})
    if not isinstance(ref, dict):
        raise kopf.PermanentError(f"externalEtcd.{field} must be an object with name/key")
    name = ref.get("name")
    if not name:
        raise kopf.PermanentError(f"externalEtcd.{field}.name is required")
    key = ref.get("key", "value")
    if not isinstance(key, str) or not key:
        raise kopf.PermanentError(f"externalEtcd.{field}.key must be a non-empty string")
    return name, key


def _normalize_external_etcd(spec: dict) -> dict | None:
    """Validate and normalize optional externalEtcd configuration."""
    config = spec.get("externalEtcd")
    if not config:
        return None
    if not isinstance(config, dict):
        raise kopf.PermanentError("externalEtcd must be an object")

    endpoints = config.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise kopf.PermanentError("externalEtcd.endpoints must be a non-empty list")
    normalized_endpoints: list[str] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, str) or not endpoint:
            raise kopf.PermanentError("externalEtcd.endpoints entries must be non-empty strings")
        normalized_endpoints.append(endpoint)

    files = config.get("files", {}) or {}
    if not isinstance(files, dict):
        raise kopf.PermanentError("externalEtcd.files must be an object when set")
    ca_file = files.get("caFile", DEFAULT_EXTERNAL_ETCD_CA_FILE)
    cert_file = files.get("certFile", DEFAULT_EXTERNAL_ETCD_CERT_FILE)
    key_file = files.get("keyFile", DEFAULT_EXTERNAL_ETCD_KEY_FILE)
    for path, field in (
        (ca_file, "caFile"),
        (cert_file, "certFile"),
        (key_file, "keyFile"),
    ):
        if not isinstance(path, str) or not path.startswith("/"):
            raise kopf.PermanentError(f"externalEtcd.files.{field} must be an absolute path")

    return {
        "endpoints": normalized_endpoints,
        "servers": ",".join(normalized_endpoints),
        "ca_ref": _required_secret_ref(config, "caCertRef"),
        "cert_ref": _required_secret_ref(config, "clientCertRef"),
        "key_ref": _required_secret_ref(config, "clientKeyRef"),
        "ca_file": ca_file,
        "cert_file": cert_file,
        "key_file": key_file,
    }


def _patch_external_etcd_in_kubeadm_yaml(yaml_text: str, external_etcd: dict) -> tuple[str, bool, bool]:
    """Patch kubeadm ClusterConfiguration with external etcd API server arguments."""
    try:
        docs = [doc for doc in yaml.safe_load_all(yaml_text) if doc is not None]
    except yaml.YAMLError:
        return yaml_text, False, False

    if not docs:
        return yaml_text, False, False

    saw_cluster_configuration = False
    changed = False
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "ClusterConfiguration":
            continue
        saw_cluster_configuration = True

        api_server = doc.setdefault("apiServer", {})
        if not isinstance(api_server, dict):
            raise kopf.PermanentError("kubeadm ClusterConfiguration.apiServer must be a mapping")
        extra_args = api_server.setdefault("extraArgs", {})
        if not isinstance(extra_args, dict):
            raise kopf.PermanentError("kubeadm ClusterConfiguration.apiServer.extraArgs must be a mapping")

        desired_args = {
            "etcd-servers": external_etcd["servers"],
            "etcd-cafile": external_etcd["ca_file"],
            "etcd-certfile": external_etcd["cert_file"],
            "etcd-keyfile": external_etcd["key_file"],
        }
        for key, value in desired_args.items():
            if extra_args.get(key) != value:
                extra_args[key] = value
                changed = True

    if not changed:
        return yaml_text, saw_cluster_configuration, False

    rendered = yaml.safe_dump_all(docs, sort_keys=False).rstrip("\n")
    return rendered, saw_cluster_configuration, True


def _patch_provider_id_in_kubeadm_yaml(yaml_text: str, provider_id: str) -> tuple[str, bool, bool]:
    """Patch kubeadm Init/JoinConfiguration nodeRegistration kubelet provider-id."""
    try:
        docs = [doc for doc in yaml.safe_load_all(yaml_text) if doc is not None]
    except yaml.YAMLError:
        return yaml_text, False, False

    if not docs:
        return yaml_text, False, False

    saw_node_registration = False
    changed = False
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") not in {"InitConfiguration", "JoinConfiguration"}:
            continue

        saw_node_registration = True
        node_registration = doc.setdefault("nodeRegistration", {})
        if not isinstance(node_registration, dict):
            raise kopf.PermanentError(
                f"kubeadm {doc.get('kind')} nodeRegistration must be a mapping",
            )
        kubelet_extra_args = node_registration.setdefault("kubeletExtraArgs", {})
        if not isinstance(kubelet_extra_args, dict):
            raise kopf.PermanentError(
                f"kubeadm {doc.get('kind')} nodeRegistration.kubeletExtraArgs must be a mapping",
            )

        if kubelet_extra_args.get("provider-id") != provider_id:
            kubelet_extra_args["provider-id"] = provider_id
            changed = True

    if not changed:
        return yaml_text, saw_node_registration, False

    rendered = yaml.safe_dump_all(docs, sort_keys=False).rstrip("\n")
    return rendered, saw_node_registration, True


def _detect_bootstrap_format(bootstrap_data: str) -> str:
    """Detect bootstrap payload format (cloud-config or shell)."""
    for line in bootstrap_data.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # kubeadm cloud-init commonly carries a leading template marker.
        if stripped.startswith("## template:"):
            continue
        if stripped.startswith("#cloud-config") or stripped.startswith(("write_files:", "runcmd:")):
            return "cloud-config"
        if stripped.startswith("#!"):
            return "shell"
        return "shell"
    return "unknown"


def _parse_cloud_config(bootstrap_data: str) -> dict:
    """Parse and validate a cloud-config payload."""
    try:
        config = yaml.safe_load(bootstrap_data) or {}
    except yaml.YAMLError as e:
        raise kopf.PermanentError(f"bootstrap cloud-config YAML is invalid: {e}") from e

    if not isinstance(config, dict):
        raise kopf.PermanentError("bootstrap cloud-config must be a mapping")

    write_files = config.get("write_files", [])
    if write_files is None:
        write_files = []
    if not isinstance(write_files, list):
        raise kopf.PermanentError("bootstrap cloud-config write_files must be a list")
    for idx, entry in enumerate(write_files):
        if not isinstance(entry, dict):
            raise kopf.PermanentError(f"bootstrap cloud-config write_files[{idx}] must be an object")
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise kopf.PermanentError(
                f"bootstrap cloud-config write_files[{idx}].path must be a non-empty string",
            )

    runcmd = config.get("runcmd", [])
    if runcmd is None:
        runcmd = []
    if not isinstance(runcmd, list):
        raise kopf.PermanentError("bootstrap cloud-config runcmd must be a list")
    for idx, command in enumerate(runcmd):
        if isinstance(command, str):
            continue
        if isinstance(command, list):
            if not all(isinstance(part, (str, int, float, bool)) for part in command):
                raise kopf.PermanentError(
                    f"bootstrap cloud-config runcmd[{idx}] list entries must be scalar values",
                )
            continue
        raise kopf.PermanentError(f"bootstrap cloud-config runcmd[{idx}] must be string or list")

    config["write_files"] = write_files
    config["runcmd"] = runcmd
    return config


def _decode_cloud_write_file_content(entry: dict, index: int) -> str:
    """Read write_files entry content, decoding supported encodings."""
    content = entry.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise kopf.PermanentError(
            f"bootstrap cloud-config write_files[{index}].content must be a string when set",
        )

    encoding = entry.get("encoding")
    if encoding is None:
        return content
    if not isinstance(encoding, str):
        raise kopf.PermanentError(
            f"bootstrap cloud-config write_files[{index}].encoding must be a string when set",
        )

    normalized = encoding.strip().lower()
    if normalized in {"", "text", "plain"}:
        return content
    if normalized in {"b64", "base64"}:
        try:
            return base64.b64decode(content).decode("utf-8")
        except Exception as e:
            raise kopf.PermanentError(
                f"bootstrap cloud-config write_files[{index}] has invalid base64 content: {e}",
            ) from e

    raise kopf.PermanentError(
        f"bootstrap cloud-config write_files[{index}] encoding '{encoding}' is unsupported",
    )


def _store_cloud_write_file_content(entry: dict, text: str) -> None:
    """Write file content back to write_files, preserving encoding convention."""
    encoding = entry.get("encoding")
    if isinstance(encoding, str) and encoding.strip().lower() in {"b64", "base64"}:
        entry["content"] = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        return
    entry["content"] = text


def _format_cloud_file_mode(mode: int | str, index: int) -> str:
    """Normalize cloud-init file mode value into chmod-compatible text."""
    if isinstance(mode, int):
        return format(mode, "o")
    if isinstance(mode, str):
        normalized = mode.strip().strip("'\"")
        if normalized:
            return normalized
    raise kopf.PermanentError(
        f"bootstrap cloud-config write_files[{index}].permissions must be a non-empty string or integer",
    )


def _render_cloud_config_to_shell(bootstrap_data: str) -> str:
    """Render supported cloud-config primitives into an executable shell script."""
    config = _parse_cloud_config(bootstrap_data)
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
    ]

    write_files = config.get("write_files", [])
    for idx, entry in enumerate(write_files):
        path = entry["path"]
        directory = posixpath.dirname(path) or "/"
        lines.append(f"install -d -m 0755 {shlex.quote(directory)}")

        marker = f"__CAPI_BOOTSTRAP_FILE_{idx}__"
        content = _decode_cloud_write_file_content(entry, idx)
        lines.append(f"cat <<'{marker}' > {shlex.quote(path)}")
        if content:
            lines.extend(content.splitlines())
        lines.append(marker)

        permissions = entry.get("permissions")
        if permissions is not None:
            lines.append(f"chmod {shlex.quote(_format_cloud_file_mode(permissions, idx))} {shlex.quote(path)}")

        owner = entry.get("owner")
        if owner is not None:
            if not isinstance(owner, str) or not owner:
                raise kopf.PermanentError(
                    f"bootstrap cloud-config write_files[{idx}].owner must be a non-empty string",
                )
            lines.append(f"chown {shlex.quote(owner)} {shlex.quote(path)}")

    for idx, command in enumerate(config.get("runcmd", [])):
        if isinstance(command, str):
            lines.append(command)
            continue
        if not command:
            continue
        rendered = " ".join(shlex.quote(str(part)) for part in command)
        if not rendered:
            raise kopf.PermanentError(f"bootstrap cloud-config runcmd[{idx}] cannot be empty")
        lines.append(rendered)

    rendered_script = "\n".join(lines).rstrip("\n")
    return f"{rendered_script}\n"


def _prepare_bootstrap_script(bootstrap_data: str) -> tuple[str, str]:
    """Normalize bootstrap payload to an executable shell script."""
    bootstrap_format = _detect_bootstrap_format(bootstrap_data)
    if bootstrap_format == "cloud-config":
        return _render_cloud_config_to_shell(bootstrap_data), bootstrap_format
    if bootstrap_format == "shell":
        if not bootstrap_data.strip():
            raise kopf.PermanentError("bootstrap data is empty")
        return bootstrap_data, bootstrap_format
    raise kopf.PermanentError("bootstrap data format is not supported")


def _bootstrap_execution_command() -> str:
    """Build bootstrap command with host-side sentinel guard."""
    sentinel_path = shlex.quote(BOOTSTRAP_SUCCESS_SENTINEL_PATH)
    sentinel_dir = shlex.quote(posixpath.dirname(BOOTSTRAP_SUCCESS_SENTINEL_PATH))
    sentinel_hit = shlex.quote(BOOTSTRAP_SENTINEL_HIT_OUTPUT)
    return (
        f"if [ -f {sentinel_path} ]; then printf '%s\\n' {sentinel_hit}; exit 0; fi && "
        "chmod +x /tmp/bootstrap.sh && /tmp/bootstrap.sh && "
        f"install -d -m 0755 {sentinel_dir} && touch {sentinel_path}"
    )


def _post_bootstrap_readiness_command() -> str:
    """Check host-side kubelet readiness after bootstrap exits successfully."""
    kubelet_ready = shlex.quote(KUBELET_READY_SENTINEL_OUTPUT)
    return (
        "if ! command -v systemctl >/dev/null 2>&1; then "
        "echo 'systemctl command not found on host' >&2; "
        "exit 31; "
        "fi && "
        "if systemctl is-active --quiet kubelet; then "
        f"printf '%s\\n' {kubelet_ready}; "
        "else "
        "(systemctl is-active kubelet || true) >&2; "
        "(systemctl --no-pager --full status kubelet 2>/dev/null | tail -n 20 || true) >&2; "
        "exit 32; "
        "fi"
    )


def _sanitize_bootstrap_diagnostic_text(text: str) -> str:
    """Redact sensitive kubeadm values before storing in status."""
    sanitized = text
    for pattern, replacement in BOOTSTRAP_DIAGNOSTIC_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return re.sub(r"\s+", " ", sanitized).strip()


def _excerpt_command_output(result: SSHResult) -> str:
    """Return a compact, sanitized stderr/stdout excerpt for diagnostics."""
    for chunk in (result.stderr, result.stdout):
        excerpt = _sanitize_bootstrap_diagnostic_text(chunk or "")
        if not excerpt:
            continue
        if len(excerpt) <= BOOTSTRAP_DIAGNOSTIC_MAX_EXCERPT:
            return excerpt
        return f"{excerpt[: BOOTSTRAP_DIAGNOSTIC_MAX_EXCERPT - 3].rstrip()}..."
    return ""


def _detect_bootstrap_failure_phase(stderr: str, stdout: str, bootstrap_script: str) -> str:
    """Infer which bootstrap phase failed from output signatures and script content."""
    combined_output = "\n".join(part for part in (stderr, stdout) if part)
    phase_signatures = (
        ("reset", (r"\bkubeadm\s+reset\b", r"\[reset\]", r"\bfailed\s+to\s+reset\b")),
        ("init", (r"\bkubeadm\s+init\b", r"\[init\]", r"\binitconfiguration\b", r"\bcontrol-plane\b")),
        ("join", (r"\bkubeadm\s+join\b", r"\[join\]", r"\bdiscovery-token\b", r"\bnode\s+join\b")),
    )
    for phase, signatures in phase_signatures:
        if any(re.search(signature, combined_output, flags=re.IGNORECASE) for signature in signatures):
            return phase

    script_lower = bootstrap_script.lower()
    has_init = "kubeadm init" in script_lower
    has_join = "kubeadm join" in script_lower
    has_reset = "kubeadm reset" in script_lower

    # Fallback prefers the primary operation over optional cleanup commands.
    if has_init and not has_join:
        return "init"
    if has_join and not has_init:
        return "join"
    if has_reset and not (has_init or has_join):
        return "reset"
    if has_init:
        return "init"
    if has_join:
        return "join"
    if has_reset:
        return "reset"
    return "unknown"


def _classify_bootstrap_failure(result: SSHResult, bootstrap_script: str) -> tuple[str, str, str, str]:
    """Classify bootstrap failures and build safe status diagnostics."""
    phase = _detect_bootstrap_failure_phase(result.stderr, result.stdout, bootstrap_script)
    reason = BOOTSTRAP_PHASE_REASON_MAP.get(phase, "BootstrapFailed")
    stderr_excerpt = _excerpt_command_output(result)
    phase_label = {
        "reset": "reset phase",
        "init": "init phase",
        "join": "join phase",
    }.get(phase, "execution")
    failure_message = f"Bootstrap {phase_label} failed (exit {result.exit_code})"
    if stderr_excerpt:
        failure_message = f"{failure_message}: {stderr_excerpt}"
    else:
        failure_message = f"{failure_message}. Inspect kubeadm and cloud-init logs on the host."
    return reason, phase, failure_message, stderr_excerpt


def _classify_kubelet_not_ready(result: SSHResult) -> tuple[str, str]:
    """Build status reason/message when post-bootstrap kubelet checks fail."""
    output_excerpt = _excerpt_command_output(result)
    failure_message = f"Bootstrap completed, but kubelet is not ready (exit {result.exit_code})"
    if output_excerpt:
        failure_message = f"{failure_message}: {output_excerpt}"
    else:
        failure_message = f"{failure_message}. Waiting for kubelet to become active."
    return "KubeletNotReady", failure_message


def _parse_heredoc_start(line: str) -> tuple[str, str] | None:
    """Parse shell heredoc forms used for writing files in bootstrap scripts."""
    direct = re.match(r'^\s*cat\s+>\s*(?P<path>\S+)\s+<<\s*["\']?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)["\']?\s*$', line)
    if direct:
        return direct.group("path"), direct.group("tag")

    reverse = re.match(r'^\s*cat\s+<<\s*["\']?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)["\']?\s+>\s*(?P<path>\S+)\s*$', line)
    if reverse:
        return reverse.group("path"), reverse.group("tag")

    return None


def _inject_external_etcd_into_shell_bootstrap_data(bootstrap_data: str, external_etcd: dict) -> tuple[str, bool]:
    """Inject external etcd wiring into shell bootstrap kubeadm heredocs."""
    lines = bootstrap_data.splitlines()
    output: list[str] = []
    idx = 0
    saw_cluster_configuration = False
    changed_any = False

    while idx < len(lines):
        line = lines[idx]
        heredoc = _parse_heredoc_start(line)
        if not heredoc:
            output.append(line)
            idx += 1
            continue

        path, tag = heredoc
        output.append(line)
        idx += 1

        body_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip() != tag:
            body_lines.append(lines[idx])
            idx += 1

        if idx >= len(lines):
            output.extend(body_lines)
            break

        if "kubeadm" in path and path.endswith((".yaml", ".yml")):
            body_text = "\n".join(body_lines)
            patched_text, saw_here, changed_here = _patch_external_etcd_in_kubeadm_yaml(body_text, external_etcd)
            saw_cluster_configuration = saw_cluster_configuration or saw_here
            changed_any = changed_any or changed_here
            if saw_here:
                body_lines = patched_text.splitlines()

        output.extend(body_lines)
        output.append(lines[idx])
        idx += 1

    if not saw_cluster_configuration:
        raise kopf.PermanentError(
            "externalEtcd is configured but bootstrap data has no kubeadm ClusterConfiguration to wire",
        )

    rendered = "\n".join(output)
    if bootstrap_data.endswith("\n"):
        rendered += "\n"
    return rendered, changed_any


def _inject_external_etcd_into_cloud_config_bootstrap_data(
    bootstrap_data: str,
    external_etcd: dict,
) -> tuple[str, bool]:
    """Inject external etcd wiring into cloud-config write_files kubeadm payloads."""
    config = _parse_cloud_config(bootstrap_data)
    write_files = config.get("write_files", [])

    saw_cluster_configuration = False
    changed_any = False
    for idx, entry in enumerate(write_files):
        path = entry.get("path")
        if not isinstance(path, str) or "kubeadm" not in path or not path.endswith((".yaml", ".yml")):
            continue

        content = _decode_cloud_write_file_content(entry, idx)
        patched_text, saw_here, changed_here = _patch_external_etcd_in_kubeadm_yaml(content, external_etcd)
        saw_cluster_configuration = saw_cluster_configuration or saw_here
        changed_any = changed_any or changed_here
        if saw_here:
            _store_cloud_write_file_content(entry, patched_text)

    if not saw_cluster_configuration:
        raise kopf.PermanentError(
            "externalEtcd is configured but bootstrap data has no kubeadm ClusterConfiguration to wire",
        )

    rendered = "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False).rstrip("\n")
    if bootstrap_data.endswith("\n"):
        rendered += "\n"
    return rendered, changed_any


def _inject_external_etcd_into_bootstrap_data(bootstrap_data: str, external_etcd: dict) -> tuple[str, bool]:
    """Inject external etcd wiring into shell or cloud-config bootstrap payload."""
    bootstrap_format = _detect_bootstrap_format(bootstrap_data)
    if bootstrap_format == "cloud-config":
        return _inject_external_etcd_into_cloud_config_bootstrap_data(bootstrap_data, external_etcd)
    return _inject_external_etcd_into_shell_bootstrap_data(bootstrap_data, external_etcd)


def _inject_provider_id_into_shell_bootstrap_data(bootstrap_data: str, provider_id: str) -> tuple[str, bool]:
    """Inject kubelet provider-id into shell bootstrap kubeadm heredocs."""
    lines = bootstrap_data.splitlines()
    output: list[str] = []
    idx = 0
    changed_any = False

    while idx < len(lines):
        line = lines[idx]
        heredoc = _parse_heredoc_start(line)
        if not heredoc:
            output.append(line)
            idx += 1
            continue

        path, tag = heredoc
        output.append(line)
        idx += 1

        body_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip() != tag:
            body_lines.append(lines[idx])
            idx += 1

        if idx >= len(lines):
            output.extend(body_lines)
            break

        if "kubeadm" in path and path.endswith((".yaml", ".yml")):
            body_text = "\n".join(body_lines)
            patched_text, saw_here, changed_here = _patch_provider_id_in_kubeadm_yaml(body_text, provider_id)
            changed_any = changed_any or changed_here
            if saw_here:
                body_lines = patched_text.splitlines()

        output.extend(body_lines)
        output.append(lines[idx])
        idx += 1

    if not changed_any:
        return bootstrap_data, False

    rendered = "\n".join(output)
    if bootstrap_data.endswith("\n"):
        rendered += "\n"
    return rendered, True


def _inject_provider_id_into_cloud_config_bootstrap_data(bootstrap_data: str, provider_id: str) -> tuple[str, bool]:
    """Inject kubelet provider-id into cloud-config kubeadm write_files payloads."""
    config = _parse_cloud_config(bootstrap_data)
    write_files = config.get("write_files", [])

    changed_any = False
    for idx, entry in enumerate(write_files):
        path = entry.get("path")
        if not isinstance(path, str) or "kubeadm" not in path or not path.endswith((".yaml", ".yml")):
            continue

        content = _decode_cloud_write_file_content(entry, idx)
        patched_text, saw_here, changed_here = _patch_provider_id_in_kubeadm_yaml(content, provider_id)
        changed_any = changed_any or changed_here
        if saw_here:
            _store_cloud_write_file_content(entry, patched_text)

    if not changed_any:
        return bootstrap_data, False

    rendered = "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False).rstrip("\n")
    if bootstrap_data.endswith("\n"):
        rendered += "\n"
    return rendered, True


def _inject_provider_id_into_bootstrap_data(bootstrap_data: str, provider_id: str) -> tuple[str, bool]:
    """Inject kubelet provider-id into shell or cloud-config bootstrap payload."""
    bootstrap_format = _detect_bootstrap_format(bootstrap_data)
    if bootstrap_format == "cloud-config":
        return _inject_provider_id_into_cloud_config_bootstrap_data(bootstrap_data, provider_id)
    return _inject_provider_id_into_shell_bootstrap_data(bootstrap_data, provider_id)


async def _upload_external_etcd_certs(conn, namespace: str, external_etcd: dict) -> None:
    """Upload external etcd cert material to deterministic paths on the target host."""
    ca_value = await _read_secret_value(namespace, *external_etcd["ca_ref"])
    cert_value = await _read_secret_value(namespace, *external_etcd["cert_ref"])
    key_value = await _read_secret_value(namespace, *external_etcd["key_ref"])

    dirs = sorted(
        {
            posixpath.dirname(external_etcd["ca_file"]),
            posixpath.dirname(external_etcd["cert_file"]),
            posixpath.dirname(external_etcd["key_file"]),
        },
    )
    for directory in dirs:
        result = await conn.execute(f"install -d -m 0700 {shlex.quote(directory)}")
        if not result.success:
            raise kopf.TemporaryError(f"failed to create external etcd directory {directory}", delay=30)

    await conn.upload(ca_value, external_etcd["ca_file"])
    await conn.upload(cert_value, external_etcd["cert_file"])
    await conn.upload(key_value, external_etcd["key_file"])

    chmod_cmd = (
        f"chmod 0644 {shlex.quote(external_etcd['ca_file'])} {shlex.quote(external_etcd['cert_file'])} "
        f"&& chmod 0600 {shlex.quote(external_etcd['key_file'])}"
    )
    chmod_result = await conn.execute(chmod_cmd)
    if not chmod_result.success:
        raise kopf.TemporaryError("failed to set external etcd certificate file permissions", delay=30)


def _set_reboot_status(patch, requested_at: str, success: bool, message: str) -> None:
    patch.status.setdefault("remediation", {})
    patch.status["remediation"]["reboot"] = {
        "lastRequestedAt": requested_at,
        "lastCompletedAt": _now_iso(),
        "success": success,
        "message": message,
    }


def _is_already_provisioned(status: dict, expected_provider_id: str) -> bool:
    """Check whether bootstrap already completed for this SSHMachine."""
    _ = expected_provider_id
    init = status.get("initialization", {})
    return bool(init.get("provisioned"))


def _has_condition_status(status: dict, condition_type: str, condition_status: str) -> bool:
    """Return True when status.conditions includes a matching type/status pair."""
    for condition in status.get("conditions", []):
        if condition.get("type") != condition_type:
            continue
        if str(condition.get("status", "")).lower() == condition_status.lower():
            return True
    return False


def _backfill_provisioned_fields(spec: dict, status: dict, patch, provider_id: str, address: str) -> bool:
    """Patch missing providerID/readiness fields on already-provisioned SSHMachines."""
    changed = False

    if spec.get("providerID") != provider_id:
        patch.spec["providerID"] = provider_id
        changed = True

    # Always include ready=True in the handler patch so kopf keeps the field in owned status.
    patch.status["ready"] = True
    if status.get("ready") is not True:
        changed = True

    init = status.get("initialization", {})
    if not bool(init.get("provisioned")):
        patch.status["initialization"] = {"provisioned": True}
        changed = True

    if (
        not _has_condition_status(status, "Ready", "True")
        or not _has_condition_status(status, MACHINE_INFRASTRUCTURE_READY_CONDITION, "True")
        or not _has_condition_status(status, MACHINE_BOOTSTRAP_EXEC_SUCCEEDED_CONDITION, "True")
    ):
        ready_message = f"Machine {address} already provisioned with providerID {provider_id}"
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=True,
            ready_reason="Provisioned",
            ready_message=ready_message,
            infrastructure_ready=True,
            infrastructure_reason="Provisioned",
            infrastructure_message=ready_message,
            bootstrap_succeeded=True,
            bootstrap_reason="BootstrapCompleted",
            bootstrap_message="Bootstrap execution has completed for this machine",
        )
        changed = True

    if status.get("failureReason") is not None:
        patch.status["failureReason"] = None
        changed = True

    if status.get("failureMessage") is not None:
        patch.status["failureMessage"] = None
        changed = True

    if status.get("bootstrapDiagnostics") is not None:
        patch.status["bootstrapDiagnostics"] = None
        changed = True

    return changed


def _reconcile_lock_key(namespace: str, name: str) -> str:
    return f"{namespace}/{name}"


def _get_reconcile_lock(namespace: str, name: str) -> asyncio.Lock:
    key = _reconcile_lock_key(namespace, name)
    lock = _RECONCILE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _RECONCILE_LOCKS[key] = lock
    return lock


def _cleanup_reconcile_lock(namespace: str, name: str, lock: asyncio.Lock | None = None) -> bool:
    """Drop a reconcile lock mapping only when no holder/waiter remains."""
    key = _reconcile_lock_key(namespace, name)
    current = _RECONCILE_LOCKS.get(key)
    if current is None:
        return False
    if lock is not None and current is not lock:
        return False
    if current.locked():
        return False
    waiters = getattr(current, "_waiters", None)
    if waiters:
        return False
    _RECONCILE_LOCKS.pop(key, None)
    return True


def _distributed_reconcile_lock_value(holder: str, expires_epoch: int) -> str:
    return f"{holder}|{expires_epoch}"


def _parse_distributed_reconcile_lock_value(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None
    holder, separator, raw_expires = value.rpartition("|")
    if not separator or not holder:
        return None
    try:
        expires_epoch = int(raw_expires)
    except ValueError:
        return None
    return holder, expires_epoch


def _acquire_distributed_reconcile_lock(namespace: str, name: str) -> bool:
    """Acquire a cross-process reconcile lock via SSHMachine metadata annotation."""
    if not SSHMACHINE_DISTRIBUTED_LOCK_ENABLED:
        return True

    api = kubernetes.client.CustomObjectsApi()
    ttl_seconds = max(30, SSHMACHINE_DISTRIBUTED_LOCK_TTL_SECONDS)

    for _ in range(5):
        obj = api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="sshmachines",
            name=name,
        )
        metadata = obj.get("metadata", {})
        resource_version = metadata.get("resourceVersion")
        if not resource_version:
            logger.warning("SSHMachine %s/%s lock acquisition skipped: missing resourceVersion", namespace, name)
            return False

        annotations = metadata.get("annotations") or {}
        lock_value = annotations.get(SSHMACHINE_DISTRIBUTED_LOCK_ANNOTATION)
        parsed = _parse_distributed_reconcile_lock_value(lock_value)
        now_epoch = int(time.time())
        if parsed is not None:
            current_holder, expires_epoch = parsed
            if current_holder != _RECONCILE_LOCK_HOLDER and expires_epoch > now_epoch:
                return False

        new_lock_value = _distributed_reconcile_lock_value(_RECONCILE_LOCK_HOLDER, now_epoch + ttl_seconds)
        body = {
            "metadata": {
                "resourceVersion": resource_version,
                "annotations": {SSHMACHINE_DISTRIBUTED_LOCK_ANNOTATION: new_lock_value},
            },
        }
        try:
            api.patch_namespaced_custom_object(
                group=API_GROUP,
                version=API_VERSION,
                namespace=namespace,
                plural="sshmachines",
                name=name,
                body=body,
            )
            return True
        except kubernetes.client.ApiException as e:
            if e.status == 409:
                continue
            if e.status == 404:
                return False
            raise

    return False


def _release_distributed_reconcile_lock(namespace: str, name: str) -> bool:
    """Release a cross-process reconcile lock when held by this controller instance."""
    if not SSHMACHINE_DISTRIBUTED_LOCK_ENABLED:
        return True

    api = kubernetes.client.CustomObjectsApi()
    for _ in range(5):
        try:
            obj = api.get_namespaced_custom_object(
                group=API_GROUP,
                version=API_VERSION,
                namespace=namespace,
                plural="sshmachines",
                name=name,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return True
            raise

        metadata = obj.get("metadata", {})
        resource_version = metadata.get("resourceVersion")
        if not resource_version:
            return False

        annotations = metadata.get("annotations") or {}
        lock_value = annotations.get(SSHMACHINE_DISTRIBUTED_LOCK_ANNOTATION)
        parsed = _parse_distributed_reconcile_lock_value(lock_value)
        if parsed is None:
            return True

        current_holder, _expires_epoch = parsed
        if current_holder != _RECONCILE_LOCK_HOLDER:
            return False

        body = {
            "metadata": {
                "resourceVersion": resource_version,
                "annotations": {SSHMACHINE_DISTRIBUTED_LOCK_ANNOTATION: None},
            },
        }
        try:
            api.patch_namespaced_custom_object(
                group=API_GROUP,
                version=API_VERSION,
                namespace=namespace,
                plural="sshmachines",
                name=name,
                body=body,
            )
            return True
        except kubernetes.client.ApiException as e:
            if e.status == 409:
                continue
            if e.status == 404:
                return True
            raise

    return False


def _acquire_distributed_lock_or_requeue(namespace: str, name: str, operation: str) -> None:
    try:
        acquired = _acquire_distributed_reconcile_lock(namespace, name)
    except Exception as e:  # noqa: BLE001
        raise kopf.TemporaryError(
            f"distributed reconcile lock acquisition failed during {operation}: {e}",
            delay=SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS,
        ) from e

    if acquired:
        return

    logger.info(
        "SSHMachine %s/%s waiting for distributed reconcile lock during %s",
        namespace,
        name,
        operation,
    )
    raise kopf.TemporaryError(
        f"distributed reconcile lock is held by another controller during {operation}",
        delay=SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS,
    )


def _release_distributed_lock_with_logging(namespace: str, name: str, operation: str) -> None:
    try:
        released = _release_distributed_reconcile_lock(namespace, name)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "SSHMachine %s/%s failed to release distributed reconcile lock during %s: %s",
            namespace,
            name,
            operation,
            e,
        )
        return

    if not released:
        logger.warning(
            "SSHMachine %s/%s distributed reconcile lock ownership changed before release during %s",
            namespace,
            name,
            operation,
        )


def _read_current_sshmachine(namespace: str, name: str) -> dict | None:
    """Read the latest SSHMachine object state from the API server."""
    api = kubernetes.client.CustomObjectsApi()
    try:
        return api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="sshmachines",
            name=name,
        )
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return None
        raise


def _machine_consumer_ref(name: str, namespace: str) -> dict:
    """Build consumerRef payload for an SSHMachine."""
    return {
        "kind": "SSHMachine",
        "name": name,
        "namespace": namespace,
    }


def _is_same_consumer(consumer_ref: dict | None, name: str, namespace: str) -> bool:
    """Return True when a consumerRef points to this SSHMachine."""
    if not consumer_ref:
        return False
    return (
        consumer_ref.get("kind", "SSHMachine") == "SSHMachine"
        and consumer_ref.get("name") == name
        and (consumer_ref.get("namespace", namespace) == namespace)
    )


def _patch_host_consumer(
    api: kubernetes.client.CustomObjectsApi,
    *,
    namespace: str,
    host_name: str,
    consumer_ref: dict,
    in_use: bool,
    resource_version: str | None,
) -> bool:
    """Patch SSHHost consumerRef with optimistic concurrency (resourceVersion).

    Clearing with `{}` is a no-op under JSON merge patch semantics for nested
    objects. Use `null` to remove spec.consumerRef keys definitively.
    """
    consumer_ref_patch: dict | None = consumer_ref if consumer_ref else None
    body: dict = {
        "spec": {
            "consumerRef": consumer_ref_patch,
        },
        "status": {
            "inUse": in_use,
        },
    }
    if resource_version:
        body["metadata"] = {"resourceVersion": resource_version}

    try:
        api.patch_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="sshhosts",
            name=host_name,
            body=body,
        )
    except kubernetes.client.ApiException as e:
        if e.status in {404, 409}:
            return False
        raise
    return True


def _apply_host_to_machine_patch(host_spec: dict, host_name: str, host_namespace: str, patch) -> None:
    """Copy claimed host fields into SSHMachine spec patch."""
    address = host_spec.get("address")
    if not address:
        raise kopf.PermanentError(f"SSHHost {host_namespace}/{host_name} is missing spec.address")
    patch.spec["address"] = address
    patch.spec["user"] = host_spec.get("user", "root")
    patch.spec["sshKeyRef"] = host_spec.get("sshKeyRef", {})
    patch.spec["hostRef"] = f"{host_namespace}/{host_name}"


def _is_consumer_orphaned(
    api: kubernetes.client.CustomObjectsApi,
    *,
    host_namespace: str,
    consumer_ref: dict,
) -> bool:
    """Return True when an SSHHost consumerRef points to a missing SSHMachine."""
    consumer_name = consumer_ref.get("name")
    if not consumer_name:
        return False
    if consumer_ref.get("kind", "SSHMachine") != "SSHMachine":
        return False

    consumer_ns = consumer_ref.get("namespace", host_namespace)
    try:
        api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=consumer_ns,
            plural="sshmachines",
            name=consumer_name,
        )
        return False
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return True
        raise


async def _choose_host(spec: dict, name: str, namespace: str, patch) -> bool:
    """Select and claim an SSHHost from the pool based on hostSelector.

    Returns True if a host was claimed (or address was already set).
    Returns False if no host is available (caller should requeue).
    """
    host_selector = spec.get("hostSelector")
    if not host_selector:
        # Direct mode: address is required when hostSelector is not used.
        if spec.get("address"):
            return True
        message = "Either address or hostSelector must be provided"
        reason = "InvalidConfiguration"
        patch.status["failureReason"] = "InvalidConfiguration"
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started because machine configuration is invalid",
        )
        raise kopf.PermanentError(message)

    match_labels = host_selector.get("matchLabels", {})
    if not match_labels:
        raise kopf.PermanentError("hostSelector.matchLabels must not be empty")

    # List all SSHHost CRs in the namespace
    api = kubernetes.client.CustomObjectsApi()
    hosts = api.list_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshhosts",
    )
    machine_consumer_ref = _machine_consumer_ref(name, namespace)

    # Sort hosts: ready first, unknown next, explicitly failed last.
    def _host_sort_key(h):
        ready = h.get("status", {}).get("ready")
        if ready is True:
            readiness_rank = 0
        elif ready is False:
            readiness_rank = 2
        else:
            readiness_rank = 1
        return (readiness_rank, h.get("metadata", {}).get("name", ""))

    # Filter by matchLabels and find unclaimed hosts
    for host in sorted(hosts.get("items", []), key=_host_sort_key):
        host_meta = host.get("metadata", {})
        host_name = host_meta.get("name")
        if not host_name:
            continue

        host_labels = host_meta.get("labels", {})
        # Check all selector labels match
        if not all(host_labels.get(k) == v for k, v in match_labels.items()):
            continue

        host_spec = host.get("spec", {})
        consumer_ref = host_spec.get("consumerRef", {})

        # Already claimed by this machine -> idempotent reuse.
        if _is_same_consumer(consumer_ref, name, namespace):
            _apply_host_to_machine_patch(host_spec, host_name, namespace, patch)
            logger.info("SSHMachine %s/%s reusing SSHHost %s", namespace, name, host_name)
            return True

        # Claimed by another machine: reclaim stale orphaned claims only.
        if consumer_ref and consumer_ref.get("name"):
            if not _is_consumer_orphaned(api, host_namespace=namespace, consumer_ref=consumer_ref):
                continue

            logger.warning(
                "SSHMachine %s/%s reclaiming stale SSHHost claim on %s from %s/%s",
                namespace,
                name,
                host_name,
                consumer_ref.get("namespace", namespace),
                consumer_ref.get("name"),
            )
            cleared = _patch_host_consumer(
                api,
                namespace=namespace,
                host_name=host_name,
                consumer_ref={},
                in_use=False,
                resource_version=host_meta.get("resourceVersion"),
            )
            if not cleared:
                continue

            try:
                host = api.get_namespaced_custom_object(
                    group=API_GROUP,
                    version=API_VERSION,
                    namespace=namespace,
                    plural="sshhosts",
                    name=host_name,
                )
            except kubernetes.client.ApiException as e:
                if e.status == 404:
                    continue
                raise

            host_meta = host.get("metadata", {})
            host_spec = host.get("spec", {})
            consumer_ref = host_spec.get("consumerRef", {})
            if consumer_ref and consumer_ref.get("name"):
                continue

        # Claim this host with optimistic concurrency.
        claimed = _patch_host_consumer(
            api,
            namespace=namespace,
            host_name=host_name,
            consumer_ref=machine_consumer_ref,
            in_use=True,
            resource_version=host_meta.get("resourceVersion"),
        )
        if not claimed:
            continue

        _apply_host_to_machine_patch(host_spec, host_name, namespace, patch)

        logger.info(
            "SSHMachine %s/%s claimed SSHHost %s (address=%s)",
            namespace,
            name,
            host_name,
            host_spec.get("address"),
        )
        return True

    # No available host found
    message = f"No unclaimed SSHHost matching {match_labels}"
    reason = "HostNotAvailable"
    patch.status["initialization"] = {"provisioned": False}
    patch.status["ready"] = False
    patch.status["conditions"] = _machine_lifecycle_conditions(
        ready=False,
        ready_reason=reason,
        ready_message=message,
        infrastructure_ready=False,
        infrastructure_reason=reason,
        infrastructure_message=message,
        bootstrap_succeeded=False,
        bootstrap_reason="BootstrapNotStarted",
        bootstrap_message="Bootstrap has not started because no SSHHost is available",
    )
    raise kopf.TemporaryError(f"No available SSHHost matching {match_labels}", delay=30)


async def _release_host(spec: dict, name: str, namespace: str) -> None:
    """Release the claimed SSHHost by clearing its consumerRef."""
    host_ref = spec.get("hostRef")
    if not host_ref:
        return

    try:
        host_ns, host_name = host_ref.split("/", 1)
    except ValueError:
        logger.warning("SSHMachine %s/%s has malformed hostRef: %s", namespace, name, host_ref)
        return

    api = kubernetes.client.CustomObjectsApi()
    for _attempt in range(3):
        try:
            host = api.get_namespaced_custom_object(
                group=API_GROUP,
                version=API_VERSION,
                namespace=host_ns,
                plural="sshhosts",
                name=host_name,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                logger.warning("SSHHost %s not found during release (already deleted?)", host_ref)
                return
            logger.warning("Failed reading SSHHost %s for release: %s", host_ref, e)
            return

        current_consumer = host.get("spec", {}).get("consumerRef", {})
        if (
            current_consumer
            and current_consumer.get("name")
            and not _is_same_consumer(current_consumer, name, namespace)
        ):
            logger.warning(
                "SSHMachine %s/%s skipped releasing SSHHost %s (owned by %s/%s)",
                namespace,
                name,
                host_ref,
                current_consumer.get("namespace", host_ns),
                current_consumer.get("name"),
            )
            return

        cleared = _patch_host_consumer(
            api,
            namespace=host_ns,
            host_name=host_name,
            consumer_ref={},
            in_use=False,
            resource_version=host.get("metadata", {}).get("resourceVersion"),
        )
        if cleared:
            logger.info("SSHMachine %s/%s released SSHHost %s", namespace, name, host_ref)
            return

    logger.warning("SSHMachine %s/%s failed to release SSHHost %s after retries", namespace, name, host_ref)


async def _sshmachine_reconcile_impl(spec, status, name, namespace, meta, patch, **_kwargs):
    """Reconcile SSHMachine -- bootstrap or verify via SSH."""
    logger.info("SSHMachine %s/%s reconciling", namespace, name)

    # Check pause
    if spec.get("paused"):
        logger.info("SSHMachine %s/%s is paused, skipping", namespace, name)
        return

    # Verify Machine owner
    owner_refs = meta.get("ownerReferences")
    if not _has_machine_owner(owner_refs):
        logger.warning("SSHMachine %s/%s has no CAPI Machine owner, waiting", namespace, name)
        message = "No CAPI Machine ownerReference found"
        reason = "WaitingForMachineOwner"
        patch.status["initialization"] = {"provisioned": False}
        patch.status["ready"] = False
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started because machine ownerReference is missing",
        )
        return

    machine_ref = _get_machine_owner_ref(owner_refs)
    machine_name = machine_ref["name"]

    try:
        bootstrap_check_strategy = _normalize_bootstrap_check_strategy(spec)
    except kopf.PermanentError as e:
        reason = "InvalidConfiguration"
        message = str(e)
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started due to invalid bootstrapCheckStrategy configuration",
        )
        raise

    # Host selection: claim an SSHHost if using hostSelector mode
    await _choose_host(spec, name, namespace, patch)

    # At this point, address must be set (either direct or from host claim)
    address = patch.spec.get("address", spec.get("address"))
    if not address:
        raise kopf.PermanentError("address is not set after host selection")

    port = spec.get("port", 22)
    user = patch.spec.get("user", spec.get("user", "root"))
    provider_id = f"ssh://{address}"

    # Idempotency: skip if already provisioned
    if _is_already_provisioned(status, provider_id):
        changed = _backfill_provisioned_fields(spec, status, patch, provider_id, address)
        if changed:
            logger.info(
                "SSHMachine %s/%s already provisioned (providerID=%s), ensured readiness/providerID persistence",
                namespace,
                name,
                provider_id,
            )
        else:
            logger.info("SSHMachine %s/%s already provisioned (providerID=%s)", namespace, name, provider_id)
        return

    # Keep diagnostics current and prevent stale bootstrap failure details.
    patch.status["bootstrapDiagnostics"] = None

    # Wait for bootstrap data
    bootstrap_data = await _read_bootstrap_data(namespace, machine_name)
    if not bootstrap_data:
        logger.info("SSHMachine %s/%s waiting for bootstrap data", namespace, name)
        reason = "WaitingForBootstrapData"
        message = f"Bootstrap data not yet available for {machine_name}"
        patch.status["initialization"] = {"provisioned": False}
        patch.status["ready"] = False
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason=reason,
            bootstrap_message=message,
        )
        raise kopf.TemporaryError("Bootstrap data not ready", delay=15)

    try:
        bootstrap_data, provider_id_changed = _inject_provider_id_into_bootstrap_data(bootstrap_data, provider_id)
        if provider_id_changed:
            logger.info(
                "SSHMachine %s/%s patched bootstrap data with kubelet provider-id %s",
                namespace,
                name,
                provider_id,
            )
    except kopf.PermanentError as e:
        reason = "ProviderIDWiringError"
        message = str(e)
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started due to providerID wiring error",
        )
        raise

    # Optional external-etcd wiring and cert distribution configuration.
    try:
        external_etcd = _normalize_external_etcd(spec)
    except kopf.PermanentError as e:
        reason = "ExternalEtcdConfigurationError"
        message = str(e)
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started due to external etcd configuration error",
        )
        raise

    if external_etcd:
        try:
            bootstrap_data, changed = _inject_external_etcd_into_bootstrap_data(bootstrap_data, external_etcd)
            if changed:
                logger.info("SSHMachine %s/%s patched bootstrap data with external etcd wiring", namespace, name)
        except kopf.PermanentError as e:
            reason = "ExternalEtcdWiringError"
            message = str(e)
            patch.status["failureReason"] = reason
            patch.status["failureMessage"] = message
            patch.status["ready"] = False
            patch.status["initialization"] = {"provisioned": False}
            patch.status["conditions"] = _machine_lifecycle_conditions(
                ready=False,
                ready_reason=reason,
                ready_message=message,
                infrastructure_ready=False,
                infrastructure_reason=reason,
                infrastructure_message=message,
                bootstrap_succeeded=False,
                bootstrap_reason="BootstrapNotStarted",
                bootstrap_message="Bootstrap has not started due to external etcd wiring error",
            )
            raise

    try:
        bootstrap_script, bootstrap_format = _prepare_bootstrap_script(bootstrap_data)
    except kopf.PermanentError as e:
        reason = "BootstrapFormatError"
        message = str(e)
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started because bootstrap data format is invalid",
        )
        raise

    logger.info("SSHMachine %s/%s bootstrap payload format: %s", namespace, name, bootstrap_format)

    # Read SSH key -- use patched sshKeyRef if set by host claim, otherwise from spec
    ssh_key_ref = patch.spec.get("sshKeyRef", spec.get("sshKeyRef", {}))
    secret_name = ssh_key_ref.get("name")
    secret_key = ssh_key_ref.get("key", "value")

    if not secret_name:
        reason = "InvalidConfiguration"
        message = "Missing sshKeyRef.name"
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = "spec.sshKeyRef.name is required"
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started because SSH key reference is missing",
        )
        raise kopf.PermanentError("spec.sshKeyRef.name is required")

    try:
        ssh_key = await _read_ssh_key(namespace, secret_name, secret_key)
    except kopf.PermanentError:
        raise
    except Exception as e:
        reason = "SSHKeyReadError"
        message = f"Failed to read SSH key secret: {e}"
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = f"Failed to read SSH key: {e}"
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason="BootstrapNotStarted",
            bootstrap_message="Bootstrap has not started because SSH key retrieval failed",
        )
        raise kopf.TemporaryError(f"SSH key read failed: {e}", delay=30) from e

    # Dry-run mode: validate prerequisites without executing the bootstrap script.
    if spec.get("dryRun"):
        try:
            async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
                pass  # Connection test only
        except Exception as e:
            reason = "DryRunSSHFailed"
            message = f"SSH connectivity check failed: {e}"
            patch.status["failureReason"] = reason
            patch.status["failureMessage"] = f"Dry-run SSH connectivity check failed: {e}"
            patch.status["ready"] = False
            patch.status["initialization"] = {"provisioned": False}
            patch.status["conditions"] = _machine_lifecycle_conditions(
                ready=False,
                ready_reason=reason,
                ready_message=message,
                infrastructure_ready=False,
                infrastructure_reason=reason,
                infrastructure_message=message,
                bootstrap_succeeded=False,
                bootstrap_reason="DryRunMode",
                bootstrap_message="Bootstrap execution is skipped in dry-run mode",
            )
            raise kopf.TemporaryError(f"Dry-run SSH failed: {e}", delay=30) from e

        dry_run_message = f"Dry-run passed: SSH to {address}, bootstrap data ready"
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason="DryRunMode",
            ready_message="Dry-run mode does not provision infrastructure",
            infrastructure_ready=False,
            infrastructure_reason="DryRunMode",
            infrastructure_message="Dry-run mode validates prerequisites without provisioning",
            bootstrap_succeeded=False,
            bootstrap_reason="DryRunMode",
            bootstrap_message="Bootstrap execution is skipped in dry-run mode",
            extras=[
                _info_condition(
                    "DryRunValidated",
                    "PreflightPassed",
                    dry_run_message,
                ),
            ],
        )
        patch.status["bootstrapDiagnostics"] = None
        patch.status["failureReason"] = None
        patch.status["failureMessage"] = None
        logger.info("SSHMachine %s/%s dry-run passed", namespace, name)
        return

    # SSH bootstrap
    try:
        async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
            if external_etcd:
                try:
                    await _upload_external_etcd_certs(conn, namespace, external_etcd)
                except kopf.PermanentError as e:
                    reason = "ExternalEtcdCertError"
                    message = str(e)
                    patch.status["failureReason"] = reason
                    patch.status["failureMessage"] = message
                    patch.status["ready"] = False
                    patch.status["initialization"] = {"provisioned": False}
                    patch.status["conditions"] = _machine_lifecycle_conditions(
                        ready=False,
                        ready_reason=reason,
                        ready_message=message,
                        infrastructure_ready=False,
                        infrastructure_reason=reason,
                        infrastructure_message=message,
                        bootstrap_succeeded=False,
                        bootstrap_reason="BootstrapNotStarted",
                        bootstrap_message="Bootstrap has not started due to external etcd certificate error",
                    )
                    raise
                except kopf.TemporaryError as e:
                    reason = "ExternalEtcdCertUploadError"
                    message = str(e)
                    patch.status["failureReason"] = reason
                    patch.status["failureMessage"] = message
                    patch.status["ready"] = False
                    patch.status["initialization"] = {"provisioned": False}
                    patch.status["conditions"] = _machine_lifecycle_conditions(
                        ready=False,
                        ready_reason=reason,
                        ready_message=message,
                        infrastructure_ready=False,
                        infrastructure_reason=reason,
                        infrastructure_message=message,
                        bootstrap_succeeded=False,
                        bootstrap_reason="BootstrapNotStarted",
                        bootstrap_message="Bootstrap has not started due to external etcd certificate upload error",
                    )
                    raise

            # Upload bootstrap script
            await conn.upload(bootstrap_script, "/tmp/bootstrap.sh")  # noqa: S108

            # Execute bootstrap
            result = await conn.execute(_bootstrap_execution_command())  # noqa: S108

            if not result.success:
                failure_reason, failure_phase, failure_message, stderr_excerpt = _classify_bootstrap_failure(
                    result,
                    bootstrap_script,
                )
                patch.status["failureReason"] = failure_reason
                patch.status["failureMessage"] = failure_message
                patch.status["bootstrapDiagnostics"] = {
                    "phase": failure_phase,
                    "exitCode": result.exit_code,
                    "stderrExcerpt": stderr_excerpt,
                }
                patch.status["ready"] = False
                patch.status["initialization"] = {"provisioned": False}
                patch.status["conditions"] = _machine_lifecycle_conditions(
                    ready=False,
                    ready_reason=failure_reason,
                    ready_message=failure_message,
                    infrastructure_ready=False,
                    infrastructure_reason=failure_reason,
                    infrastructure_message=failure_message,
                    bootstrap_succeeded=False,
                    bootstrap_reason=failure_reason,
                    bootstrap_message=failure_message,
                )
                raise kopf.TemporaryError(
                    f"Bootstrap failed ({failure_reason}, exit {result.exit_code})",
                    delay=30,
                )

            if BOOTSTRAP_SENTINEL_HIT_OUTPUT in (result.stdout or ""):
                logger.info(
                    "SSHMachine %s/%s bootstrap sentinel already present on %s, skipping bootstrap script",
                    namespace,
                    name,
                    address,
                )

            if bootstrap_check_strategy == BOOTSTRAP_CHECK_STRATEGY_SSH:
                readiness_result = await conn.execute(_post_bootstrap_readiness_command())  # noqa: S108
                if not readiness_result.success:
                    failure_reason, failure_message = _classify_kubelet_not_ready(readiness_result)
                    patch.status["initialization"] = {"provisioned": False}
                    patch.status["failureReason"] = failure_reason
                    patch.status["failureMessage"] = failure_message
                    patch.status["ready"] = False
                    patch.status["conditions"] = _machine_lifecycle_conditions(
                        ready=False,
                        ready_reason=failure_reason,
                        ready_message=failure_message,
                        infrastructure_ready=False,
                        infrastructure_reason=failure_reason,
                        infrastructure_message=failure_message,
                        bootstrap_succeeded=True,
                        bootstrap_reason="BootstrapCompleted",
                        bootstrap_message="Bootstrap script completed; waiting for kubelet readiness checks to pass",
                        extras=[
                            _info_condition(
                                "Bootstrapped",
                                "BootstrapCompleted",
                                "Bootstrap script completed; waiting for kubelet readiness checks to pass",
                            ),
                        ],
                    )
                    raise kopf.TemporaryError(
                        f"Post-bootstrap readiness check failed ({failure_reason}, exit {readiness_result.exit_code})",
                        delay=30,
                    )
            else:
                logger.info(
                    "SSHMachine %s/%s skipping post-bootstrap readiness check (bootstrapCheckStrategy=none)",
                    namespace,
                    name,
                )

    except kopf.TemporaryError:
        raise
    except kopf.PermanentError:
        raise
    except TimeoutError as e:
        reason = "SSHTimeout"
        message = str(e)
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = f"SSH operation timed out: {e}"
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason=reason,
            bootstrap_message="Bootstrap execution was interrupted by SSH timeout",
        )
        raise kopf.TemporaryError(f"SSH timeout: {e}", delay=30) from e
    except Exception as e:
        reason = "SSHError"
        message = f"SSH connection failed: {e}"
        patch.status["failureReason"] = reason
        patch.status["failureMessage"] = message
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            bootstrap_succeeded=False,
            bootstrap_reason=reason,
            bootstrap_message="Bootstrap execution could not proceed due to SSH error",
        )
        raise kopf.TemporaryError(f"SSH error: {e}", delay=30) from e

    # Success
    patch.spec["providerID"] = provider_id
    patch.status["initialization"] = {"provisioned": True}
    patch.status["ready"] = True
    patch.status["addresses"] = [
        {"type": "InternalIP", "address": address},
    ]
    success_message = f"Machine {address} provisioned with providerID {provider_id}"
    bootstrap_success_message = "Bootstrap execution and readiness checks completed successfully"
    success_extras: list[dict] | None = None
    if bootstrap_check_strategy == BOOTSTRAP_CHECK_STRATEGY_NONE:
        bootstrap_success_message = (
            "Bootstrap execution completed; post-bootstrap readiness checks skipped (bootstrapCheckStrategy=none)"
        )
        success_extras = [
            _info_condition(
                "BootstrapCheckSkipped",
                "StrategyNone",
                "Post-bootstrap readiness checks skipped by spec.bootstrapCheckStrategy=none",
            ),
        ]
    patch.status["conditions"] = _machine_lifecycle_conditions(
        ready=True,
        ready_reason="Provisioned",
        ready_message=success_message,
        infrastructure_ready=True,
        infrastructure_reason="Provisioned",
        infrastructure_message=success_message,
        bootstrap_succeeded=True,
        bootstrap_reason="BootstrapCompleted",
        bootstrap_message=bootstrap_success_message,
        extras=success_extras,
    )
    # Clear any previous failure state
    patch.status["bootstrapDiagnostics"] = None
    patch.status["failureReason"] = None
    patch.status["failureMessage"] = None

    logger.info("SSHMachine %s/%s provisioned: providerID=%s", namespace, name, provider_id)


@kopf.on.create(API_GROUP, API_VERSION, "sshmachines")
@kopf.on.update(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_reconcile(spec, status, name, namespace, meta, patch, **_kwargs):
    """Serialized SSHMachine reconcile entrypoint for create/update events."""
    lock = _get_reconcile_lock(namespace, name)
    if lock.locked():
        logger.info("SSHMachine %s/%s waiting for active reconcile to finish", namespace, name)

    try:
        async with lock:
            _acquire_distributed_lock_or_requeue(namespace, name, "reconcile")
            try:
                # Refresh live object state when an event UID is available to reject stale timer/handler events.
                event_uid = meta.get("uid")
                if event_uid:
                    try:
                        latest = _read_current_sshmachine(namespace, name)
                    except Exception as e:
                        raise kopf.TemporaryError(
                            f"failed to refresh live SSHMachine state under reconcile lock: {e}",
                            delay=15,
                        ) from e
                    else:
                        if latest is None:
                            logger.info(
                                "SSHMachine %s/%s no longer exists while reconciling, skipping stale event",
                                namespace,
                                name,
                            )
                            return

                        live_meta = latest.get("metadata", {})
                        live_uid = live_meta.get("uid")
                        if live_uid and event_uid != live_uid:
                            logger.info(
                                "SSHMachine %s/%s stale reconcile event detected (eventUID=%s liveUID=%s), skipping",
                                namespace,
                                name,
                                event_uid,
                                live_uid,
                            )
                            return

                        spec = latest.get("spec", spec)
                        status = latest.get("status", status)
                        meta = live_meta or meta
                        logger.info("SSHMachine %s/%s refreshed live state under reconcile lock", namespace, name)
                else:
                    logger.debug(
                        "SSHMachine %s/%s reconcile event has no metadata.uid, skipping stale-event UID validation",
                        namespace,
                        name,
                    )

                await _sshmachine_reconcile_impl(
                    spec=spec,
                    status=status,
                    name=name,
                    namespace=namespace,
                    meta=meta,
                    patch=patch,
                )
            finally:
                _release_distributed_lock_with_logging(namespace, name, "reconcile")
    finally:
        _cleanup_reconcile_lock(namespace, name, lock)


@kopf.timer(
    API_GROUP,
    API_VERSION,
    "sshmachines",
    interval=SSHMACHINE_RECONCILE_INTERVAL,
    initial_delay=15,
)
async def sshmachine_reconcile_timer(spec, status, name, namespace, meta, patch, **_kwargs):
    """Periodic reconcile to recover from missed create/update event races."""
    await sshmachine_reconcile(
        spec=spec,
        status=status,
        name=name,
        namespace=namespace,
        meta=meta,
        patch=patch,
    )


@kopf.on.delete(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_delete(spec, name, namespace, patch=None, **_kwargs):
    """Handle SSHMachine deletion -- cleanup via SSH (kubeadm reset) and release host."""
    logger.info("SSHMachine %s/%s deleting", namespace, name)
    if patch is not None:
        patch.status["ready"] = False
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = _machine_lifecycle_conditions(
            ready=False,
            ready_reason="Deleting",
            ready_message="Infrastructure machine is deleting",
            infrastructure_ready=False,
            infrastructure_reason="Deleting",
            infrastructure_message="Infrastructure machine is deleting",
            bootstrap_succeeded=False,
            bootstrap_reason="Deleting",
            bootstrap_message="Bootstrap lifecycle is terminating due to machine deletion",
        )

    lock = _get_reconcile_lock(namespace, name)
    if lock.locked():
        logger.info("SSHMachine %s/%s waiting for in-flight reconcile before delete cleanup", namespace, name)

    try:
        async with lock:
            _acquire_distributed_lock_or_requeue(namespace, name, "delete")
            try:
                # Release the claimed SSHHost back to the pool
                await _release_host(spec, name, namespace)

                address = spec.get("address")
                port = spec.get("port", 22)
                user = spec.get("user", "root")
                ssh_key_ref = spec.get("sshKeyRef", {})
                secret_name = ssh_key_ref.get("name")
                secret_key = ssh_key_ref.get("key", "value")

                if not address or not secret_name:
                    logger.warning("SSHMachine %s/%s missing address or sshKeyRef, skipping cleanup", namespace, name)
                    return

                try:
                    ssh_key = await _read_ssh_key(namespace, secret_name, secret_key)
                except Exception as e:
                    logger.warning("SSHMachine %s/%s failed to read SSH key for cleanup: %s", namespace, name, e)
                    # Don't block finalizer removal if we can't read the key
                    return

                try:
                    async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
                        cleanup_cmd = (
                            "kubeadm reset -f && rm -rf /etc/kubernetes /var/lib/kubelet "
                            f"{shlex.quote(BOOTSTRAP_SUCCESS_SENTINEL_PATH)}"
                        )
                        result = await conn.execute(cleanup_cmd)
                        if result.success:
                            logger.info("SSHMachine %s/%s cleanup succeeded on %s", namespace, name, address)
                        else:
                            logger.warning(
                                "SSHMachine %s/%s cleanup failed on %s (exit=%d), allowing finalizer removal",
                                namespace,
                                name,
                                address,
                                result.exit_code,
                            )
                except Exception as e:
                    # Cleanup failures must not block finalizer removal
                    logger.warning("SSHMachine %s/%s SSH cleanup error on %s: %s", namespace, name, address, e)
            finally:
                _release_distributed_lock_with_logging(namespace, name, "delete")
    finally:
        _cleanup_reconcile_lock(namespace, name, lock)


@kopf.on.field(API_GROUP, API_VERSION, "sshmachines", field="spec.remediation.reboot.requestedAt")
async def sshmachine_reboot(old, new, spec, name, namespace, patch, **_kwargs):
    """Handle explicit in-band reboot requests for remediation."""
    if not new or new == old:
        return

    if spec.get("paused"):
        _set_reboot_status(patch, str(new), False, "Machine is paused; reboot request ignored")
        return

    address = spec.get("address")
    port = spec.get("port", 22)
    user = spec.get("user", "root")
    ssh_key_ref = spec.get("sshKeyRef", {})
    secret_name = ssh_key_ref.get("name")
    secret_key = ssh_key_ref.get("key", "value")

    if not address or not secret_name:
        _set_reboot_status(
            patch,
            str(new),
            False,
            "Missing spec.address or spec.sshKeyRef.name; cannot perform reboot remediation",
        )
        raise kopf.TemporaryError("reboot remediation waiting for address/sshKeyRef", delay=15)

    try:
        ssh_key = await _read_ssh_key(namespace, secret_name, secret_key)
    except Exception as e:
        _set_reboot_status(patch, str(new), False, f"Failed to read SSH key: {e}")
        raise kopf.TemporaryError(f"failed to read SSH key for reboot remediation: {e}", delay=30) from e

    try:
        async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
            reboot_cmd = "nohup sh -c 'sleep 2; (systemctl reboot || reboot)' >/dev/null 2>&1 &"
            result = await conn.execute(reboot_cmd)
            if not result.success:
                _set_reboot_status(
                    patch,
                    str(new),
                    False,
                    f"Reboot command failed with exit code {result.exit_code}",
                )
                raise kopf.TemporaryError("reboot remediation command failed", delay=30)
    except kopf.TemporaryError:
        raise
    except Exception as e:
        _set_reboot_status(patch, str(new), False, f"SSH reboot remediation failed: {e}")
        raise kopf.TemporaryError(f"SSH reboot remediation failed: {e}", delay=30) from e

    _set_reboot_status(patch, str(new), True, "Reboot command submitted")
    logger.info("SSHMachine %s/%s reboot remediation requested at %s", namespace, name, new)


@kopf.on.field(API_GROUP, API_VERSION, "sshmachines", field="spec.paused")
async def sshmachine_pause(old, new, name, namespace, **_kwargs):
    """Handle pause/unpause of SSHMachine."""
    if new:
        logger.info("SSHMachine %s/%s paused", namespace, name)
    else:
        logger.info("SSHMachine %s/%s unpaused", namespace, name)
