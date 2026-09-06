"""Real Kopf handlers, real CAPI owner chain, real API status persistence."""

import time

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
    assert "kopf" not in obj["status"], "Progress must not rely on a pruned status field"


def test_owner_pause_resume_is_observed_without_infra_spec_change(api_runtime):
    rt = api_runtime
    cluster_pair(rt, paused=True)
    try:
        time.sleep(4)
        assert not rt.get(SSH_GROUP, "sshclusters", "infra").get("status", {}).get("ready")
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
    assert obj["status"]["conditions"][0]["reason"] == "WaitingForClusterOwner"
