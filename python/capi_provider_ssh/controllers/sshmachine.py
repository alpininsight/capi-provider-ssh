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

import kopf
import kubernetes
import yaml

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.ssh import SSHClient

logger = logging.getLogger(__name__)

DEFAULT_EXTERNAL_ETCD_CA_FILE = "/etc/kubernetes/pki/etcd-external/ca.crt"
DEFAULT_EXTERNAL_ETCD_CERT_FILE = "/etc/kubernetes/pki/etcd-external/client.crt"
DEFAULT_EXTERNAL_ETCD_KEY_FILE = "/etc/kubernetes/pki/etcd-external/client.key"
SSHMACHINE_RECONCILE_INTERVAL = int(
    os.environ.get("SSHMACHINE_RECONCILE_INTERVAL", os.environ.get("RECONCILE_INTERVAL", "60")),
)
_RECONCILE_LOCKS: dict[str, asyncio.Lock] = {}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _ready_condition(message: str) -> dict:
    return {
        "type": "Ready",
        "status": "True",
        "lastTransitionTime": _now_iso(),
        "reason": "Provisioned",
        "message": message,
    }


def _not_ready_condition(reason: str, message: str) -> dict:
    return {
        "type": "Ready",
        "status": "False",
        "lastTransitionTime": _now_iso(),
        "reason": reason,
        "message": message,
    }


def _info_condition(condition_type: str, reason: str, message: str) -> dict:
    return {
        "type": condition_type,
        "status": "True",
        "lastTransitionTime": _now_iso(),
        "reason": reason,
        "message": message,
    }


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
    """Patch SSHHost consumerRef with optimistic concurrency (resourceVersion)."""
    body: dict = {
        "spec": {
            "consumerRef": consumer_ref,
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
        patch.status["failureReason"] = "InvalidConfiguration"
        patch.status["failureMessage"] = "Either address or hostSelector must be provided"
        patch.status["conditions"] = [
            _not_ready_condition("InvalidConfiguration", "Either address or hostSelector must be provided"),
        ]
        raise kopf.PermanentError("Either address or hostSelector must be provided")

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
    patch.status["initialization"] = {"provisioned": False}
    patch.status["conditions"] = [
        _not_ready_condition("HostNotAvailable", f"No unclaimed SSHHost matching {match_labels}"),
    ]
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
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = [
            _not_ready_condition("WaitingForMachineOwner", "No CAPI Machine ownerReference found"),
        ]
        return

    machine_ref = _get_machine_owner_ref(owner_refs)
    machine_name = machine_ref["name"]

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
        logger.info("SSHMachine %s/%s already provisioned (providerID=%s)", namespace, name, provider_id)
        return

    # Wait for bootstrap data
    bootstrap_data = await _read_bootstrap_data(namespace, machine_name)
    if not bootstrap_data:
        logger.info("SSHMachine %s/%s waiting for bootstrap data", namespace, name)
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = [
            _not_ready_condition("WaitingForBootstrapData", f"Bootstrap data not yet available for {machine_name}"),
        ]
        raise kopf.TemporaryError("Bootstrap data not ready", delay=15)

    # Optional external-etcd wiring and cert distribution configuration.
    try:
        external_etcd = _normalize_external_etcd(spec)
    except kopf.PermanentError as e:
        patch.status["failureReason"] = "ExternalEtcdConfigurationError"
        patch.status["failureMessage"] = str(e)
        patch.status["conditions"] = [
            _not_ready_condition("ExternalEtcdConfigurationError", str(e)),
        ]
        raise

    if external_etcd:
        try:
            bootstrap_data, changed = _inject_external_etcd_into_bootstrap_data(bootstrap_data, external_etcd)
            if changed:
                logger.info("SSHMachine %s/%s patched bootstrap data with external etcd wiring", namespace, name)
        except kopf.PermanentError as e:
            patch.status["failureReason"] = "ExternalEtcdWiringError"
            patch.status["failureMessage"] = str(e)
            patch.status["conditions"] = [
                _not_ready_condition("ExternalEtcdWiringError", str(e)),
            ]
            raise

    try:
        bootstrap_script, bootstrap_format = _prepare_bootstrap_script(bootstrap_data)
    except kopf.PermanentError as e:
        patch.status["failureReason"] = "BootstrapFormatError"
        patch.status["failureMessage"] = str(e)
        patch.status["conditions"] = [
            _not_ready_condition("BootstrapFormatError", str(e)),
        ]
        raise

    logger.info("SSHMachine %s/%s bootstrap payload format: %s", namespace, name, bootstrap_format)

    # Read SSH key -- use patched sshKeyRef if set by host claim, otherwise from spec
    ssh_key_ref = patch.spec.get("sshKeyRef", spec.get("sshKeyRef", {}))
    secret_name = ssh_key_ref.get("name")
    secret_key = ssh_key_ref.get("key", "value")

    if not secret_name:
        patch.status["failureReason"] = "InvalidConfiguration"
        patch.status["failureMessage"] = "spec.sshKeyRef.name is required"
        patch.status["conditions"] = [
            _not_ready_condition("InvalidConfiguration", "Missing sshKeyRef.name"),
        ]
        raise kopf.PermanentError("spec.sshKeyRef.name is required")

    try:
        ssh_key = await _read_ssh_key(namespace, secret_name, secret_key)
    except kopf.PermanentError:
        raise
    except Exception as e:
        patch.status["failureReason"] = "SSHKeyReadError"
        patch.status["failureMessage"] = f"Failed to read SSH key: {e}"
        patch.status["conditions"] = [
            _not_ready_condition("SSHKeyReadError", f"Failed to read SSH key secret: {e}"),
        ]
        raise kopf.TemporaryError(f"SSH key read failed: {e}", delay=30) from e

    # Dry-run mode: validate prerequisites without executing the bootstrap script.
    if spec.get("dryRun"):
        try:
            async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
                pass  # Connection test only
        except Exception as e:
            patch.status["failureReason"] = "DryRunSSHFailed"
            patch.status["failureMessage"] = f"Dry-run SSH connectivity check failed: {e}"
            patch.status["conditions"] = [
                _not_ready_condition("DryRunSSHFailed", f"SSH connectivity check failed: {e}"),
            ]
            raise kopf.TemporaryError(f"Dry-run SSH failed: {e}", delay=30) from e

        patch.status["conditions"] = [
            _info_condition(
                "DryRunValidated",
                "PreflightPassed",
                f"Dry-run passed: SSH to {address}, bootstrap data ready",
            ),
        ]
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
                    patch.status["failureReason"] = "ExternalEtcdCertError"
                    patch.status["failureMessage"] = str(e)
                    patch.status["conditions"] = [
                        _not_ready_condition("ExternalEtcdCertError", str(e)),
                    ]
                    raise
                except kopf.TemporaryError as e:
                    patch.status["failureReason"] = "ExternalEtcdCertUploadError"
                    patch.status["failureMessage"] = str(e)
                    patch.status["conditions"] = [
                        _not_ready_condition("ExternalEtcdCertUploadError", str(e)),
                    ]
                    raise

            # Upload bootstrap script
            await conn.upload(bootstrap_script, "/tmp/bootstrap.sh")  # noqa: S108

            # Execute bootstrap
            result = await conn.execute("chmod +x /tmp/bootstrap.sh && /tmp/bootstrap.sh")  # noqa: S108

            if not result.success:
                patch.status["failureReason"] = "BootstrapFailed"
                patch.status["failureMessage"] = f"Bootstrap script exited {result.exit_code}"
                patch.status["conditions"] = [
                    _not_ready_condition("BootstrapFailed", f"Bootstrap script exited with code {result.exit_code}"),
                ]
                raise kopf.TemporaryError(f"Bootstrap failed (exit {result.exit_code})", delay=30)

    except kopf.TemporaryError:
        raise
    except kopf.PermanentError:
        raise
    except TimeoutError as e:
        patch.status["failureReason"] = "SSHTimeout"
        patch.status["failureMessage"] = f"SSH operation timed out: {e}"
        patch.status["conditions"] = [
            _not_ready_condition("SSHTimeout", str(e)),
        ]
        raise kopf.TemporaryError(f"SSH timeout: {e}", delay=30) from e
    except Exception as e:
        patch.status["failureReason"] = "SSHError"
        patch.status["failureMessage"] = f"SSH connection failed: {e}"
        patch.status["conditions"] = [
            _not_ready_condition("SSHError", f"SSH connection failed: {e}"),
        ]
        raise kopf.TemporaryError(f"SSH error: {e}", delay=30) from e

    # Success
    patch.spec["providerID"] = provider_id
    patch.status["initialization"] = {"provisioned": True}
    patch.status["addresses"] = [
        {"type": "InternalIP", "address": address},
    ]
    patch.status["conditions"] = [
        _ready_condition(f"Machine {address} provisioned with providerID {provider_id}"),
    ]
    # Clear any previous failure state
    patch.status["failureReason"] = None
    patch.status["failureMessage"] = None

    logger.info("SSHMachine %s/%s provisioned: providerID=%s", namespace, name, provider_id)


@kopf.on.create(API_GROUP, API_VERSION, "sshmachines")
@kopf.on.update(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_reconcile(spec, status, name, namespace, meta, patch, **_kwargs):
    """Serialized SSHMachine reconcile entrypoint for create/update events."""
    lock = _get_reconcile_lock(namespace, name)
    waited_for_lock = lock.locked()
    if waited_for_lock:
        logger.info("SSHMachine %s/%s waiting for active reconcile to finish", namespace, name)

    async with lock:
        if waited_for_lock:
            try:
                latest = _read_current_sshmachine(namespace, name)
            except Exception as e:
                logger.warning(
                    "SSHMachine %s/%s failed to refresh live state after reconcile wait: %s",
                    namespace,
                    name,
                    e,
                )
            else:
                if latest is not None:
                    spec = latest.get("spec", spec)
                    status = latest.get("status", status)
                    meta = latest.get("metadata", meta)
                    logger.info("SSHMachine %s/%s refreshed live state after reconcile wait", namespace, name)

        await _sshmachine_reconcile_impl(
            spec=spec,
            status=status,
            name=name,
            namespace=namespace,
            meta=meta,
            patch=patch,
        )


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
async def sshmachine_delete(spec, name, namespace, **_kwargs):
    """Handle SSHMachine deletion -- cleanup via SSH (kubeadm reset) and release host."""
    logger.info("SSHMachine %s/%s deleting", namespace, name)
    lock = _get_reconcile_lock(namespace, name)
    if lock.locked():
        logger.info("SSHMachine %s/%s waiting for in-flight reconcile before delete cleanup", namespace, name)

    try:
        async with lock:
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
                    cleanup_cmd = "kubeadm reset -f && rm -rf /etc/kubernetes /var/lib/kubelet"
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
