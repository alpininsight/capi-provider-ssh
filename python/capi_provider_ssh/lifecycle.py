"""Restart-safe cleanup and reboot, invoked under the Machine's reconcile lock."""

from __future__ import annotations

import base64
import datetime
import re

import kopf
import kubernetes

from capi_provider_ssh.contracts import get_object, is_paused, persist_machine_status, read_known_hosts
from capi_provider_ssh.inventory import bind_machine, recover_unstarted_claim, release_host, set_host_phase
from capi_provider_ssh.operations import host_operation, owned_command
from capi_provider_ssh.ssh import SSHClient


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def connect(binding: dict, namespace: str):
    ref = binding.get("sshKeyRef") or {}
    if not ref.get("name"):
        raise kopf.PermanentError("Allocated target has no SSH key reference")
    secret = kubernetes.client.CoreV1Api().read_namespaced_secret(name=ref["name"], namespace=namespace)
    key = base64.b64decode(secret.data[ref.get("key", "value")], validate=True).decode()
    return await SSHClient.connect(
        address=binding["address"],
        port=binding.get("port", 22),
        user=binding.get("user", "root"),
        key=key,
        known_hosts=read_known_hosts(namespace, binding),
    )


def check_current(namespace: str, name: str, uid: str) -> dict:
    current = get_object("sshmachines", namespace, name)
    if current["metadata"].get("uid") != uid:
        raise kopf.TemporaryError("Machine identity changed before remote execution", delay=15)
    if is_paused(current["spec"], current["metadata"], namespace):
        raise kopf.TemporaryError("Machine operation is paused by CAPI", delay=15)
    return current


def write_reboot(namespace, name, uid, patch, state):
    persist_machine_status(namespace, name, uid, {"remediation": {"reboot": state}})
    patch.status.setdefault("remediation", {})["reboot"] = state


async def reconcile_reboot(spec, status, name, namespace, meta, patch, *, observe_only=False):
    previous = status.get("remediation", {}).get("reboot") or {}
    requested = spec.get("remediation", {}).get("reboot", {}).get("requestedAt")
    if observe_only:
        requested = previous.get("lastRequestedAt")
    if not requested or is_paused(spec, meta, namespace) or (spec.get("dryRun") and not observe_only):
        return
    uid = meta["uid"]
    ownership = status.get("bootstrapOwnership") or {}
    if ownership.get("machineUID") != uid or not status.get("initialization", {}).get("provisioned"):
        raise kopf.TemporaryError("Reboot requires a provisioned, UID-owned allocation", delay=15)
    binding = bind_machine(spec, status, name, namespace, uid, patch)
    same_request = previous.get("lastRequestedAt") == requested
    if same_request and previous.get("phase") in {"Succeeded", "Failed"}:
        return
    pending = previous.get("phase") in {"Prepared", "Submitted", "Unknown"}
    async with host_operation(binding, uid) as operation, await connect(binding, namespace) as conn:
        check_current(namespace, name, uid)
        await operation.check()
        observed = await conn.execute(owned_command(uid, "cat /proc/sys/kernel/random/boot_id"))
        boot_id = observed.stdout.strip()
        if not observed.success or not re.fullmatch(r"[0-9a-fA-F-]{36}", boot_id):
            raise kopf.TemporaryError("Cannot establish host boot identity", delay=15)
        if pending:
            if boot_id != previous.get("previousBootID"):
                previous = {
                    **previous,
                    "phase": "Succeeded",
                    "success": True,
                    "lastCompletedAt": now(),
                    "observedBootID": boot_id,
                    "message": "A new host boot ID was observed",
                }
                write_reboot(namespace, name, uid, patch, previous)
                return
            if same_request:
                age = (
                    datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(previous["startedAt"])
                ).total_seconds()
                if age >= 300:
                    previous = {
                        **previous,
                        "phase": "Unknown",
                        "success": False,
                        "message": "No new boot observed; request will not be replayed automatically",
                    }
                    write_reboot(namespace, name, uid, patch, previous)
                    return
                raise kopf.TemporaryError("Waiting to observe the requested host reboot", delay=15)
            if previous.get("phase") != "Unknown":
                raise kopf.TemporaryError("A previous reboot is still in progress", delay=15)
        if observe_only:
            return
        state = {
            "lastRequestedAt": requested,
            "phase": "Prepared",
            "previousBootID": boot_id,
            "startedAt": now(),
            "success": False,
            "lastCompletedAt": None,
            "message": "Reboot intent persisted before command submission",
        }
        write_reboot(namespace, name, uid, patch, state)
        await operation.check()
        try:
            result = await conn.execute(
                owned_command(uid, "nohup sh -c 'sleep 2; (systemctl reboot || reboot)' >/dev/null 2>&1 &")
            )
        except Exception as exc:
            state.update(phase="Unknown", message="Command outcome unknown; observe boot ID before retrying")
            write_reboot(namespace, name, uid, patch, state)
            raise kopf.TemporaryError("Reboot submission outcome is unknown", delay=15) from exc
        if not result.success:
            state.update(phase="Failed", message=f"Reboot command rejected (exit {result.exit_code})")
        else:
            state.update(phase="Submitted", message="Reboot submitted; completion not yet observed")
        write_reboot(namespace, name, uid, patch, state)


async def delete_machine(spec, status, name, namespace, meta, patch):
    """Retain claim and finalizer until cleanup succeeds, including partial bootstrap."""
    if is_paused(spec, meta, namespace):
        raise kopf.TemporaryError("Deletion is paused by CAPI", delay=15)
    uid = meta["uid"]
    binding = status.get("allocation") or {}
    ownership = status.get("bootstrapOwnership") or {}
    if binding and binding.get("machineUID") != uid:
        raise kopf.TemporaryError("Cannot delete a different Machine UID's allocation", delay=30)
    if not ownership:
        provisioned = status.get("initialization", {}).get("provisioned") or spec.get("providerID")
        if not provisioned and not binding and (spec.get("hostRef") or spec.get("hostSelector")):
            binding = recover_unstarted_claim(name, namespace, uid)
            if binding:
                if spec.get("hostRef") and spec["hostRef"] != binding["hostRef"]:
                    raise kopf.TemporaryError("Unstarted host claim differs from the selected host", delay=30)
                persist_machine_status(namespace, name, uid, {"allocation": binding})
        if provisioned or (spec.get("hostRef") and not binding):
            if binding:
                set_host_phase(binding, name, namespace, uid, "Quarantined", "LegacyOwnershipUnverified")
            raise kopf.TemporaryError("Legacy host ownership is unverified; explicit recovery required", delay=30)
        release_host(binding, name, namespace, uid)
        return  # Includes dry-run/prerequisite failures: no remote mutation was recorded.
    if not binding or ownership.get("machineUID") != uid:
        raise kopf.TemporaryError("Cannot establish bootstrap ownership for cleanup", delay=30)
    for field in ("address", "port", "hostUID"):
        if ownership.get(field) != binding.get(field):
            raise kopf.TemporaryError("Cleanup target differs from bootstrap ownership", delay=30)
    if status.get("cleanup", {}).get("phase") == "Succeeded":
        release_host(binding, name, namespace, uid)
        return
    reboot = status.get("remediation", {}).get("reboot") or {}
    if reboot.get("phase") in {"Prepared", "Submitted", "Unknown"}:
        # Observe pending completion during deletion, without submitting another reboot.
        await reconcile_reboot(spec, status, name, namespace, meta, patch, observe_only=True)
        raise kopf.TemporaryError("Cleanup waits for a resolved reboot outcome", delay=15)
    patch.status["ready"] = False
    set_host_phase(binding, name, namespace, uid, "Cleaning")
    persist_machine_status(namespace, name, uid, {"cleanup": {"phase": "Running"}})
    try:
        async with host_operation(binding, uid) as operation, await connect(binding, namespace) as conn:
            check_current(namespace, name, uid)
            await operation.check()
            command = (
                "kubeadm reset -f && test ! -d /var/lib/etcd/member && rm -rf /etc/kubernetes /var/lib/kubelet "
                "/run/cluster-api/bootstrap-success.complete && "
                "rm -rf /var/lib/capi-provider-ssh"
            )
            result = await conn.execute(owned_command(uid, command, cleaned_retry=True))
            if not result.success:
                raise kopf.TemporaryError(f"Host cleanup failed (exit {result.exit_code})", delay=30)
            persist_machine_status(namespace, name, uid, {"cleanup": {"phase": "Succeeded"}})
            patch.status["cleanup"] = {"phase": "Succeeded"}
            release_host(binding, name, namespace, uid)
    except Exception as exc:
        set_host_phase(binding, name, namespace, uid, "Quarantined", "CleanupFailed")
        persist_machine_status(namespace, name, uid, {"cleanup": {"phase": "Failed"}})
        patch.status["cleanup"] = {"phase": "Failed"}
        raise kopf.TemporaryError("Cleanup incomplete; host remains claimed and quarantined", delay=30) from exc
