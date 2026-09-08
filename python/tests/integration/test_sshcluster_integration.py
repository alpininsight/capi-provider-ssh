"""Real Kopf handlers, real CAPI owner chain, real API status persistence."""

import pytest

from tests.kind.runtime import CAPI_GROUP, SSH_GROUP, eventually

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]


def cluster_pair(rt, *, paused=False):
    cluster = rt.create(
        CAPI_GROUP,
        "clusters",
        "Cluster",
        "cluster",
        {
            "paused": paused,
            "infrastructureRef": {"apiVersion": f"{SSH_GROUP}/v1beta1", "kind": "SSHCluster", "name": "infra"},
        },
    )
    return rt.create(
        SSH_GROUP,
        "sshclusters",
        "SSHCluster",
        "infra",
        {
            "controlPlaneEndpoint": {"host": "192.0.2.10", "port": 6443},
        },
        metadata={
            "ownerReferences": [
                {
                    "apiVersion": f"{CAPI_GROUP}/v1beta1",
                    "kind": "Cluster",
                    "name": "cluster",
                    "uid": cluster["metadata"]["uid"],
                }
            ]
        },
    )


def test_kopf_persists_cluster_ready(api_runtime):
    rt = api_runtime
    cluster_pair(rt)
    obj = eventually(
        "Kopf persists infrastructure readiness",
        lambda: x if (x := rt.get(SSH_GROUP, "sshclusters", "infra")).get("status", {}).get("ready") else None,
    )
    assert obj["status"]["initialization"]["provisioned"] is True
    ready = next(item for item in obj["status"]["conditions"] if item["type"] == "Ready")
    assert ready["observedGeneration"] == obj["metadata"]["generation"]
    assert "kopf" not in obj["status"], "Progress must not rely on a pruned status field"


def test_owner_pause_resume_is_observed_without_infra_spec_change(api_runtime):
    rt = api_runtime
    cluster_pair(rt, paused=True)
    try:
        obj = eventually("paused condition persisted", lambda: observed_condition(rt, "Paused", "True"))
        assert not obj.get("status", {}).get("ready")
    finally:
        rt.patch(CAPI_GROUP, "clusters", "cluster", {"spec": {"paused": False}})
    eventually("owner unpause", lambda: rt.get(SSH_GROUP, "sshclusters", "infra").get("status", {}).get("ready"))


def test_no_owner_is_never_marked_ready(api_runtime):
    rt = api_runtime
    rt.create(
        SSH_GROUP, "sshclusters", "SSHCluster", "orphan", {"controlPlaneEndpoint": {"host": "192.0.2.10", "port": 6443}}
    )
    obj = eventually(
        "owner gate persisted",
        lambda: x if (x := rt.get(SSH_GROUP, "sshclusters", "orphan")).get("status", {}).get("conditions") else None,
    )
    assert not obj["status"]["ready"]
    ready = next(item for item in obj["status"]["conditions"] if item["type"] == "Ready")
    assert ready["reason"] == "WaitingForClusterOwner"


def observed_condition(rt, kind, status):
    obj = rt.get(SSH_GROUP, "sshclusters", "infra")
    for item in obj.get("status", {}).get("conditions", []):
        if (
            item["type"] == kind
            and item["status"] == status
            and item.get("observedGeneration") == obj["metadata"]["generation"]
        ):
            return obj
    return None


def test_pause_preserves_ready_and_resume_updates_observed_generation(api_runtime):
    rt = api_runtime
    cluster_pair(rt)
    obj = eventually("initial ready observation", lambda: observed_condition(rt, "Ready", "True"))
    ready = next(item for item in obj["status"]["conditions"] if item["type"] == "Ready")
    rt.patch(SSH_GROUP, "sshclusters", "infra", {"spec": {"paused": True}})
    try:
        paused = eventually("pause observation", lambda: observed_condition(rt, "Paused", "True"))
        assert next(item for item in paused["status"]["conditions"] if item["type"] == "Ready") == ready
        assert paused["status"]["ready"] is True
    finally:
        rt.patch(SSH_GROUP, "sshclusters", "infra", {"spec": {"paused": False}})
    resumed = eventually("resumed ready observation", lambda: observed_condition(rt, "Ready", "True"))
    assert (
        next(item for item in resumed["status"]["conditions"] if item["type"] == "Ready")["lastTransitionTime"]
        == ready["lastTransitionTime"]
    )
