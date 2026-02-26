"""Tests for SSHCluster controller."""

import kopf

from capi_provider_ssh.controllers.sshcluster import (
    _has_capi_cluster_owner,
    _reconcile,
)


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
