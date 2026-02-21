"""SSHHost controller -- periodic health probing of SSH hosts.

Runs a timer-based probe on each SSHHost to check SSH connectivity.
Updates status.ready, status.lastProbeTime, and status.lastProbeSuccess
so that _choose_host in the SSHMachine controller can prefer reachable hosts.
"""

import logging
import os

import kopf

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.controllers.sshmachine import _now_iso, _read_ssh_key
from capi_provider_ssh.ssh import SSHClient

logger = logging.getLogger(__name__)

SSHHOST_PROBE_INTERVAL = int(os.environ.get("SSHHOST_PROBE_INTERVAL", "300"))
SSHHOST_PROBE_TIMEOUT = int(os.environ.get("SSHHOST_PROBE_TIMEOUT", "10"))


@kopf.timer(API_GROUP, API_VERSION, "sshhosts", interval=SSHHOST_PROBE_INTERVAL, initial_delay=10)
async def sshhost_probe(spec, status, name, namespace, patch, **_kwargs):
    """Periodically probe SSH connectivity on an SSHHost."""
    address = spec.get("address")
    port = spec.get("port", 22)
    user = spec.get("user", "root")
    ssh_key_ref = spec.get("sshKeyRef", {})
    secret_name = ssh_key_ref.get("name")
    secret_key = ssh_key_ref.get("key", "value")

    if not address or not secret_name:
        logger.warning("SSHHost %s/%s missing address or sshKeyRef, skipping probe", namespace, name)
        return

    now = _now_iso()

    try:
        ssh_key = await _read_ssh_key(namespace, secret_name, secret_key)
    except Exception as e:
        logger.warning("SSHHost %s/%s failed to read SSH key for probe: %s", namespace, name, e)
        patch.status["ready"] = False
        patch.status["lastProbeTime"] = now
        patch.status["lastProbeSuccess"] = False
        patch.status["conditions"] = [
            {
                "type": "SSHReachable",
                "status": "False",
                "lastTransitionTime": now,
                "reason": "SSHKeyReadError",
                "message": f"Failed to read SSH key: {e}",
            },
        ]
        return

    try:
        async with await SSHClient.connect(
            address=address,
            port=port,
            user=user,
            key=ssh_key,
            timeout=SSHHOST_PROBE_TIMEOUT,
        ) as _conn:
            pass  # Connection test only

        patch.status["ready"] = True
        patch.status["lastProbeTime"] = now
        patch.status["lastProbeSuccess"] = True
        patch.status["conditions"] = [
            {
                "type": "SSHReachable",
                "status": "True",
                "lastTransitionTime": now,
                "reason": "ProbeSucceeded",
                "message": f"SSH probe to {address}:{port} succeeded",
            },
        ]
        logger.debug("SSHHost %s/%s probe succeeded", namespace, name)

    except Exception as e:
        patch.status["ready"] = False
        patch.status["lastProbeTime"] = now
        patch.status["lastProbeSuccess"] = False
        patch.status["conditions"] = [
            {
                "type": "SSHReachable",
                "status": "False",
                "lastTransitionTime": now,
                "reason": "ProbeFailed",
                "message": f"SSH probe to {address}:{port} failed: {e}",
            },
        ]
        logger.warning("SSHHost %s/%s probe failed: %s", namespace, name, e)
