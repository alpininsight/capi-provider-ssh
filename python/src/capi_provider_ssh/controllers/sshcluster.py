"""SSHCluster controller -- reconciles SSHCluster resources.

The SSHCluster is largely a passthrough: the control plane endpoint is
user-specified (the target host already exists), so the controller just
verifies ownership and marks infrastructure as ready.
"""

import datetime
import logging

import kopf

from capi_provider_ssh import API_GROUP, API_VERSION

logger = logging.getLogger(__name__)

FINALIZER = f"{API_GROUP}/sshcluster-controller"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _has_capi_cluster_owner(owner_references: list[dict] | None) -> bool:
    """Check if the resource has a CAPI Cluster owner reference."""
    if not owner_references:
        return False
    return any(
        ref.get("apiVersion", "").startswith("cluster.x-k8s.io/")
        and ref.get("kind") == "Cluster"
        for ref in owner_references
    )


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


def _reconcile(spec: dict, name: str, namespace: str, meta: dict, patch: kopf.Patch) -> None:
    """Idempotent reconciliation logic for SSHCluster."""
    if spec.get("paused"):
        logger.info("SSHCluster %s/%s is paused, skipping reconciliation", namespace, name)
        return

    owner_refs = meta.get("ownerReferences")
    if not _has_capi_cluster_owner(owner_refs):
        logger.warning("SSHCluster %s/%s has no CAPI Cluster owner, waiting", namespace, name)
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = [
            _not_ready_condition("WaitingForClusterOwner", "No CAPI Cluster ownerReference found"),
        ]
        return

    endpoint = spec.get("controlPlaneEndpoint", {})
    host = endpoint.get("host", "")
    port = endpoint.get("port", 0)

    if not host or not port:
        patch.status["initialization"] = {"provisioned": False}
        patch.status["conditions"] = [
            _not_ready_condition("InvalidEndpoint", f"Invalid controlPlaneEndpoint: {host}:{port}"),
        ]
        return

    patch.status["initialization"] = {"provisioned": True}
    patch.status["conditions"] = [
        _ready_condition(f"Control plane endpoint {host}:{port} registered"),
    ]
    logger.info("SSHCluster %s/%s reconciled: endpoint=%s:%d", namespace, name, host, port)


@kopf.on.create(API_GROUP, API_VERSION, "sshclusters")
async def sshcluster_create(spec, name, namespace, meta, patch, **_kwargs):
    """Handle SSHCluster creation."""
    logger.info("SSHCluster %s/%s created", namespace, name)
    _reconcile(spec, name, namespace, meta, patch)


@kopf.on.update(API_GROUP, API_VERSION, "sshclusters")
async def sshcluster_update(spec, name, namespace, meta, patch, **_kwargs):
    """Handle SSHCluster updates -- re-reconcile idempotently."""
    logger.info("SSHCluster %s/%s updated", namespace, name)
    _reconcile(spec, name, namespace, meta, patch)


@kopf.on.delete(API_GROUP, API_VERSION, "sshclusters")
async def sshcluster_delete(name, namespace, **_kwargs):
    """Handle SSHCluster deletion -- no-op cleanup."""
    logger.info("SSHCluster %s/%s deleted (no-op cleanup)", namespace, name)
