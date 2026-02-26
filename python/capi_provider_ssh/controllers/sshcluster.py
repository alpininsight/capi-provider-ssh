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
CLUSTER_INFRASTRUCTURE_READY_CONDITION = "InfrastructureReady"
CLUSTER_ENDPOINT_READY_CONDITION = "ControlPlaneEndpointReady"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _has_capi_cluster_owner(owner_references: list[dict] | None) -> bool:
    """Check if the resource has a CAPI Cluster owner reference."""
    if not owner_references:
        return False
    return any(
        ref.get("apiVersion", "").startswith("cluster.x-k8s.io/") and ref.get("kind") == "Cluster"
        for ref in owner_references
    )


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


def _cluster_lifecycle_conditions(
    *,
    ready: bool,
    ready_reason: str,
    ready_message: str,
    infrastructure_ready: bool,
    infrastructure_reason: str,
    infrastructure_message: str,
    endpoint_ready: bool,
    endpoint_reason: str,
    endpoint_message: str,
) -> list[dict]:
    return [
        _condition("Ready", "True" if ready else "False", ready_reason, ready_message),
        _condition(
            CLUSTER_INFRASTRUCTURE_READY_CONDITION,
            "True" if infrastructure_ready else "False",
            infrastructure_reason,
            infrastructure_message,
        ),
        _condition(
            CLUSTER_ENDPOINT_READY_CONDITION,
            "True" if endpoint_ready else "False",
            endpoint_reason,
            endpoint_message,
        ),
    ]


def _reconcile(spec: dict, name: str, namespace: str, meta: dict, patch: kopf.Patch) -> None:
    """Idempotent reconciliation logic for SSHCluster."""
    if spec.get("paused"):
        logger.info("SSHCluster %s/%s is paused, skipping reconciliation", namespace, name)
        return

    owner_refs = meta.get("ownerReferences")
    if not _has_capi_cluster_owner(owner_refs):
        logger.warning("SSHCluster %s/%s has no CAPI Cluster owner, waiting", namespace, name)
        message = "No CAPI Cluster ownerReference found"
        reason = "WaitingForClusterOwner"
        patch.status["initialization"] = {"provisioned": False}
        patch.status["ready"] = False
        patch.status["conditions"] = _cluster_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            endpoint_ready=False,
            endpoint_reason=reason,
            endpoint_message="Control plane endpoint cannot be evaluated before owner is available",
        )
        return

    endpoint = spec.get("controlPlaneEndpoint", {})
    host = endpoint.get("host", "")
    port = endpoint.get("port", 0)

    if not host or not port:
        reason = "InvalidEndpoint"
        message = f"Invalid controlPlaneEndpoint: {host}:{port}"
        patch.status["initialization"] = {"provisioned": False}
        patch.status["ready"] = False
        patch.status["conditions"] = _cluster_lifecycle_conditions(
            ready=False,
            ready_reason=reason,
            ready_message=message,
            infrastructure_ready=False,
            infrastructure_reason=reason,
            infrastructure_message=message,
            endpoint_ready=False,
            endpoint_reason=reason,
            endpoint_message=message,
        )
        return

    message = f"Control plane endpoint {host}:{port} registered"
    patch.status["initialization"] = {"provisioned": True}
    patch.status["ready"] = True
    patch.status["conditions"] = _cluster_lifecycle_conditions(
        ready=True,
        ready_reason="Provisioned",
        ready_message=message,
        infrastructure_ready=True,
        infrastructure_reason="Provisioned",
        infrastructure_message=message,
        endpoint_ready=True,
        endpoint_reason="EndpointConfigured",
        endpoint_message=message,
    )
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
async def sshcluster_delete(name, namespace, patch=None, **_kwargs):
    """Handle SSHCluster deletion -- no-op cleanup."""
    if patch is not None:
        patch.status["initialization"] = {"provisioned": False}
        patch.status["ready"] = False
        patch.status["conditions"] = _cluster_lifecycle_conditions(
            ready=False,
            ready_reason="Deleting",
            ready_message="Cluster infrastructure is deleting",
            infrastructure_ready=False,
            infrastructure_reason="Deleting",
            infrastructure_message="Cluster infrastructure is deleting",
            endpoint_ready=False,
            endpoint_reason="Deleting",
            endpoint_message="Control plane endpoint is being removed",
        )
    logger.info("SSHCluster %s/%s deleted (no-op cleanup)", namespace, name)
