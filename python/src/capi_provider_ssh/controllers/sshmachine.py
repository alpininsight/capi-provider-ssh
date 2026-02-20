"""SSHMachine controller -- reconciles SSHMachine resources.

This is the core controller of the provider. It handles:
- Bootstrap via SSH (kubeadm init/join)
- Cleanup via SSH (kubeadm reset)
- Status management (providerID, addresses, conditions)
"""

import datetime
import logging

import kopf
import kubernetes

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.ssh import SSHClient

logger = logging.getLogger(__name__)


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
    import base64

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

    import base64

    return base64.b64decode(secret.data["value"]).decode("utf-8")


def _is_already_provisioned(status: dict, expected_provider_id: str) -> bool:
    """Check if machine is already provisioned with matching providerID."""
    init = status.get("initialization", {})
    if not init.get("provisioned"):
        return False
    # Check conditions for Ready=True
    conditions = status.get("conditions", [])
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)


@kopf.on.create(API_GROUP, API_VERSION, "sshmachines")
@kopf.on.update(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_reconcile(spec, status, name, namespace, meta, patch, **_kwargs):
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

    # Set providerID
    address = spec["address"]
    port = spec.get("port", 22)
    user = spec.get("user", "root")
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

    # Read SSH key
    ssh_key_ref = spec.get("sshKeyRef", {})
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

    # SSH bootstrap
    try:
        async with await SSHClient.connect(address=address, port=port, user=user, key=ssh_key) as conn:
            # Upload bootstrap script
            await conn.upload(bootstrap_data, "/tmp/bootstrap.sh")  # noqa: S108

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


@kopf.on.delete(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_delete(spec, name, namespace, **_kwargs):
    """Handle SSHMachine deletion -- cleanup via SSH (kubeadm reset)."""
    logger.info("SSHMachine %s/%s deleting", namespace, name)

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


@kopf.on.field(API_GROUP, API_VERSION, "sshmachines", field="spec.paused")
async def sshmachine_pause(old, new, name, namespace, **_kwargs):
    """Handle pause/unpause of SSHMachine."""
    if new:
        logger.info("SSHMachine %s/%s paused", namespace, name)
    else:
        logger.info("SSHMachine %s/%s unpaused", namespace, name)
