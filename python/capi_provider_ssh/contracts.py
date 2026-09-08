"""Shared CAPI pause, object identity and API persistence contracts."""

from __future__ import annotations

import base64

import kopf
import kubernetes

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.conditions import merge_conditions

PAUSED_ANNOTATION = "cluster.x-k8s.io/paused"
CLUSTER_LABEL = "cluster.x-k8s.io/cluster-name"


def get_object(plural: str, namespace: str, name: str, *, group=API_GROUP, version=API_VERSION) -> dict:
    return kubernetes.client.CustomObjectsApi().get_namespaced_custom_object(
        group=group,
        version=version,
        namespace=namespace,
        plural=plural,
        name=name,
    )


def is_paused(spec: dict, meta: dict, namespace: str) -> bool:
    """Honor standard CAPI pause throughout the owner chain; missing owners block work."""
    if spec.get("paused") or PAUSED_ANNOTATION in (meta.get("annotations") or {}):
        return True
    cluster_name = (meta.get("labels") or {}).get(CLUSTER_LABEL)
    cluster_version = "v1beta1"
    for owner in meta.get("ownerReferences", []):
        if not owner.get("apiVersion", "").startswith("cluster.x-k8s.io/"):
            continue
        kind = owner.get("kind")
        if kind not in {"Machine", "Cluster"}:
            continue
        version = owner["apiVersion"].split("/", 1)[1]
        try:
            obj = get_object(kind.lower() + "s", namespace, owner["name"], group="cluster.x-k8s.io", version=version)
        except kubernetes.client.ApiException as exc:
            if exc.status == 404:
                return True
            raise kopf.TemporaryError("Cannot establish CAPI owner pause state", delay=15) from exc
        if owner.get("uid") and obj["metadata"].get("uid") != owner["uid"]:
            raise kopf.TemporaryError("CAPI owner UID changed; waiting for a current owner reference", delay=15)
        if obj.get("spec", {}).get("paused") or PAUSED_ANNOTATION in (obj["metadata"].get("annotations") or {}):
            return True
        if kind == "Cluster":
            return False
        cluster_name = obj.get("spec", {}).get("clusterName") or cluster_name
        cluster_version = version
    if cluster_name:
        try:
            cluster = get_object("clusters", namespace, cluster_name, group="cluster.x-k8s.io", version=cluster_version)
        except kubernetes.client.ApiException as exc:
            if exc.status == 404:
                return True
            raise kopf.TemporaryError("Cannot establish Cluster pause state", delay=15) from exc
        return bool(cluster.get("spec", {}).get("paused")) or PAUSED_ANNOTATION in (
            cluster.get("metadata", {}).get("annotations") or {}
        )
    return False


def persist_machine_status(namespace: str, name: str, uid: str, changes: dict) -> dict:
    """Commit safety state before remote side effects, with UID and version fencing."""
    if not uid:
        raise kopf.PermanentError("SSHMachine metadata.uid is required for lifecycle operations")
    current = get_object("sshmachines", namespace, name)
    if current["metadata"].get("uid") != uid:
        raise kopf.TemporaryError("SSHMachine UID changed before status persistence", delay=15)
    changes = dict(changes)
    if "conditions" in changes:
        changes["conditions"] = merge_conditions(current.get("status", {}).get("conditions", []), changes["conditions"])
    try:
        return kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="sshmachines",
            name=name,
            body={
                "metadata": {"uid": uid, "resourceVersion": current["metadata"]["resourceVersion"]},
                "status": changes,
            },
        )
    except kubernetes.client.ApiException as exc:
        raise kopf.TemporaryError(
            "Lifecycle state could not be persisted; no new remote operation started", delay=15
        ) from exc


def read_known_hosts(namespace: str, spec: dict) -> str:
    """Read independently verified OpenSSH known_hosts entries, including host CAs."""
    ref = spec.get("sshHostKeyRef") or {}
    if not ref.get("name"):
        raise kopf.PermanentError("spec.sshHostKeyRef.name is required; automatic host-key trust is disabled")
    key = ref.get("key", "known_hosts")
    secret = kubernetes.client.CoreV1Api().read_namespaced_secret(name=ref["name"], namespace=namespace)
    if not secret.data or not secret.data.get(key):
        raise kopf.PermanentError("Host trust Secret does not contain the configured known_hosts entry")
    return base64.b64decode(secret.data[key], validate=True).decode("utf-8")
