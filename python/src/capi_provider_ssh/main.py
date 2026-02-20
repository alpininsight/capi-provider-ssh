"""Kopf entrypoint for capi-provider-ssh."""

import logging
import os

import kopf

from capi_provider_ssh import API_GROUP, API_VERSION

logger = logging.getLogger(__name__)

# Runtime configuration (environment variables)
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "30"))
SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "300"))
RECONCILE_INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "10"))


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_kwargs):
    """Configure kopf operator settings."""
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270
    settings.watching.client_timeout = 300


@kopf.on.create(API_GROUP, API_VERSION, "sshclusters")
async def sshcluster_create(spec, name, namespace, patch, **_kwargs):
    """Handle SSHCluster creation -- mark infrastructure as ready."""
    logger.info("SSHCluster %s/%s created", namespace, name)
    # SSHCluster is mostly a passthrough: the control plane endpoint
    # is user-specified, so we just mark it as provisioned.
    patch.status["initialization"] = {"provisioned": True}
    patch.status["conditions"] = [
        {
            "type": "Ready",
            "status": "True",
            "reason": "Provisioned",
            "message": f"Control plane endpoint {spec['controlPlaneEndpoint']['host']}:"
            f"{spec['controlPlaneEndpoint']['port']} registered",
        }
    ]


@kopf.on.delete(API_GROUP, API_VERSION, "sshclusters")
async def sshcluster_delete(name, namespace, **_kwargs):
    """Handle SSHCluster deletion."""
    logger.info("SSHCluster %s/%s deleted", namespace, name)


@kopf.on.create(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_create(spec, name, namespace, patch, **_kwargs):
    """Handle SSHMachine creation -- provision via SSH."""
    logger.info("SSHMachine %s/%s created, address=%s", namespace, name, spec.get("address"))

    if spec.get("paused"):
        logger.info("SSHMachine %s/%s is paused, skipping", namespace, name)
        return

    # Set providerID
    address = spec["address"]
    provider_id = f"ssh://{address}"
    patch.spec["providerID"] = provider_id

    # Set addresses in status
    patch.status["addresses"] = [
        {"type": "InternalIP", "address": address},
    ]

    # TODO(#3): actual SSH bootstrap via SSHMachine controller
    # For now, mark as provisioned (will be replaced by real logic)
    patch.status["initialization"] = {"provisioned": True}
    patch.status["conditions"] = [
        {
            "type": "Ready",
            "status": "True",
            "reason": "Provisioned",
            "message": f"Machine {address} provisioned with providerID {provider_id}",
        }
    ]


@kopf.on.delete(API_GROUP, API_VERSION, "sshmachines")
async def sshmachine_delete(spec, name, namespace, **_kwargs):
    """Handle SSHMachine deletion -- cleanup via SSH."""
    logger.info("SSHMachine %s/%s deleted, address=%s", namespace, name, spec.get("address"))
    # TODO(#3): kubeadm reset via SSH


@kopf.on.field(API_GROUP, API_VERSION, "sshmachines", field="spec.paused")
async def sshmachine_pause(old, new, name, namespace, **_kwargs):
    """Handle pause/unpause of SSHMachine."""
    if new:
        logger.info("SSHMachine %s/%s paused", namespace, name)
    else:
        logger.info("SSHMachine %s/%s unpaused", namespace, name)
