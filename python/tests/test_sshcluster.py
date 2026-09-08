"""Tests for SSHCluster controller."""

from unittest.mock import patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshcluster import (
    _has_capi_cluster_owner,
    _reconcile,
)


@pytest.fixture(autouse=True)
def existing_capi_cluster():
    with patch(
        "capi_provider_ssh.contracts.get_object",
        return_value={
            "metadata": {"uid": "abc-123"},
            "spec": {},
        },
    ):
        yield


def _conditions_by_type(status: dict) -> dict[str, dict]:
    return {condition["type"]: condition for condition in status.get("conditions", [])}


class TestHasCapiClusterOwner:
    def test_with_cluster_owner(self, sshcluster_meta_with_owner):
        assert _has_capi_cluster_owner(sshcluster_meta_with_owner["ownerReferences"]) is True

    def test_without_owner(self):
        assert _has_capi_cluster_owner(None) is False

    def test_empty_list(self):
        assert _has_capi_cluster_owner([]) is False

    def test_wrong_kind(self):
        refs = [{"apiVersion": "cluster.x-k8s.io/v1beta1", "kind": "Machine", "name": "m"}]
        assert _has_capi_cluster_owner(refs) is False

    def test_wrong_api_group(self):
        refs = [{"apiVersion": "apps/v1", "kind": "Cluster", "name": "c"}]
        assert _has_capi_cluster_owner(refs) is False


class TestSSHClusterReconcile:
    def test_paused_skips_reconciliation(self, sshcluster_meta_with_owner):
        spec = {"controlPlaneEndpoint": {"host": "10.0.0.1", "port": 6443}, "paused": True}
        patch = kopf.Patch({})
        _reconcile(spec, "test", "default", sshcluster_meta_with_owner, patch)
        # Should not set any status when paused
        assert "status" not in patch or "initialization" not in patch.get("status", {})

    def test_no_owner_not_ready(self, sshcluster_spec, sshcluster_meta_no_owner):
        patch = kopf.Patch({})
        _reconcile(sshcluster_spec, "test", "default", sshcluster_meta_no_owner, patch)
        assert patch["status"]["initialization"]["provisioned"] is False
        assert patch["status"]["ready"] is False
        conditions = _conditions_by_type(patch["status"])
        assert conditions["Ready"]["reason"] == "WaitingForClusterOwner"
        assert conditions["InfrastructureReady"]["status"] == "False"
        assert conditions["ControlPlaneEndpointReady"]["status"] == "False"

    def test_valid_cluster_provisioned(self, sshcluster_spec, sshcluster_meta_with_owner):
        patch = kopf.Patch({})
        _reconcile(sshcluster_spec, "test", "default", sshcluster_meta_with_owner, patch)
        assert patch["status"]["initialization"]["provisioned"] is True
        assert patch["status"]["ready"] is True
        conditions = _conditions_by_type(patch["status"])
        assert conditions["Ready"]["status"] == "True"
        assert conditions["Ready"]["reason"] == "Provisioned"
        assert conditions["InfrastructureReady"]["status"] == "True"
        assert conditions["ControlPlaneEndpointReady"]["status"] == "True"

    def test_invalid_endpoint_not_ready(self, sshcluster_meta_with_owner):
        spec = {"controlPlaneEndpoint": {"host": "", "port": 0}}
        patch = kopf.Patch({})
        _reconcile(spec, "test", "default", sshcluster_meta_with_owner, patch)
        assert patch["status"]["initialization"]["provisioned"] is False
        assert patch["status"]["ready"] is False
        conditions = _conditions_by_type(patch["status"])
        assert conditions["Ready"]["reason"] == "InvalidEndpoint"
        assert conditions["InfrastructureReady"]["status"] == "False"
        assert conditions["ControlPlaneEndpointReady"]["status"] == "False"

    def test_idempotent_reconciliation(self, sshcluster_spec, sshcluster_meta_with_owner):
        """Running reconcile twice produces same result."""
        patch1 = kopf.Patch({})
        patch2 = kopf.Patch({})
        _reconcile(sshcluster_spec, "test", "default", sshcluster_meta_with_owner, patch1)
        _reconcile(sshcluster_spec, "test", "default", sshcluster_meta_with_owner, patch2)
        assert patch1["status"]["initialization"] == patch2["status"]["initialization"]

    def test_condition_has_timestamp(self, sshcluster_spec, sshcluster_meta_with_owner):
        patch = kopf.Patch({})
        _reconcile(sshcluster_spec, "test", "default", sshcluster_meta_with_owner, patch)
        for condition in patch["status"]["conditions"]:
            assert "lastTransitionTime" in condition


def test_pause_and_resume_preserve_transition_times_and_foreign_conditions(sshcluster_spec, sshcluster_meta_with_owner):
    meta = {**sshcluster_meta_with_owner, "generation": 1}
    first = kopf.Patch()
    _reconcile(sshcluster_spec, "test", "default", meta, first)
    status = dict(first.status)
    ready = _conditions_by_type(status)["Ready"].copy()
    foreign = {"type": "ConsumerHealthy", "status": "True", "reason": "Healthy"}
    status["conditions"].append(foreign)
    paused = kopf.Patch()
    meta["generation"] = 2
    _reconcile({**sshcluster_spec, "paused": True}, "test", "default", meta, paused, status)
    values = _conditions_by_type(paused.status)
    assert values["Ready"] == ready
    assert values["Paused"]["status"] == "True"
    assert values["Paused"]["observedGeneration"] == 2
    assert values["ConsumerHealthy"] == foreign
    resumed = kopf.Patch()
    _reconcile(sshcluster_spec, "test", "default", meta, resumed, {**status, **paused.status})
    values = _conditions_by_type(resumed.status)
    assert values["Paused"]["status"] == "False"
    assert values["Ready"]["observedGeneration"] == 2
    assert values["Ready"]["lastTransitionTime"] == ready["lastTransitionTime"]
    assert values["ConsumerHealthy"] == foreign


@pytest.mark.parametrize("paused", [False, True])
async def test_cluster_delete_reports_cleanup_and_pause(sshcluster_spec, sshcluster_meta_with_owner, paused):
    from capi_provider_ssh.controllers.sshcluster import sshcluster_delete

    result = kopf.Patch()
    kwargs = dict(
        name="test",
        namespace="default",
        spec={**sshcluster_spec, "paused": paused},
        meta={**sshcluster_meta_with_owner, "generation": 7},
        patch=result,
    )
    if paused:
        with pytest.raises(kopf.TemporaryError, match="paused"):
            await sshcluster_delete(**kwargs)
    else:
        await sshcluster_delete(**kwargs)
    values = _conditions_by_type(result.status)
    assert result.status["ready"] is False
    assert values["Ready"]["status"] == "False"
    assert values["Paused"]["status"] == ("True" if paused else "False")
    assert values["CleanupSucceeded"]["status"] == ("False" if paused else "True")
    assert values["CleanupSucceeded"]["observedGeneration"] == 7
