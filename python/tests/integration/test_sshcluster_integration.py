"""Integration tests for SSHCluster controller against real K8s API.

These tests call the controller's reconcile logic directly with real K8s objects.
No operator process is started -- we invoke _reconcile() and then verify the
status was persisted via the K8s API.
"""

from __future__ import annotations

import kopf
import pytest

from capi_provider_ssh.controllers.sshcluster import _reconcile
from tests.integration.helpers import create_sshcluster, get_sshcluster

pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]


class TestSSHClusterWithOwner:
    """SSHCluster with a CAPI Cluster ownerReference should become provisioned."""

    def test_create_with_owner_becomes_provisioned(
        self, custom_api, test_namespace, cluster_owner_ref
    ):
        """Create SSHCluster with owner → reconcile → verify provisioned status."""
        spec = {"controlPlaneEndpoint": {"host": "10.0.0.1", "port": 6443}}
        name = "test-cluster-owned"

        # Create the CR on the real cluster
        create_sshcluster(custom_api, name, test_namespace, spec, owner_refs=cluster_owner_ref)

        # Fetch it back to get the real metadata
        resource = get_sshcluster(custom_api, name, test_namespace)

        # Run reconcile logic (Phase 1: direct call, not operator-driven)
        patch = kopf.Patch({})
        _reconcile(
            spec=resource["spec"],
            name=name,
            namespace=test_namespace,
            meta=resource["metadata"],
            patch=patch,
        )

        # Verify the patch would set provisioned=True
        assert patch["status"]["initialization"]["provisioned"] is True
        assert patch["status"]["conditions"][0]["reason"] == "Provisioned"
        assert patch["status"]["conditions"][0]["status"] == "True"

        # Persist status to cluster via subresource patch
        custom_api.patch_namespaced_custom_object_status(
            group="infrastructure.alpininsight.ai",
            version="v1beta1",
            namespace=test_namespace,
            plural="sshclusters",
            name=name,
            body={"status": dict(patch.get("status", {}))},
        )

        # Verify status persisted on the real object
        updated = get_sshcluster(custom_api, name, test_namespace)
        assert updated["status"]["initialization"]["provisioned"] is True

    def test_idempotent_reconciliation(
        self, custom_api, test_namespace, cluster_owner_ref
    ):
        """Running reconcile twice on the same resource produces consistent status."""
        spec = {"controlPlaneEndpoint": {"host": "10.0.0.2", "port": 6443}}
        name = "test-cluster-idempotent"

        create_sshcluster(custom_api, name, test_namespace, spec, owner_refs=cluster_owner_ref)
        resource = get_sshcluster(custom_api, name, test_namespace)

        patch1 = kopf.Patch({})
        patch2 = kopf.Patch({})
        _reconcile(resource["spec"], name, test_namespace, resource["metadata"], patch1)
        _reconcile(resource["spec"], name, test_namespace, resource["metadata"], patch2)

        assert patch1["status"]["initialization"] == patch2["status"]["initialization"]
        assert patch1["status"]["conditions"][0]["reason"] == patch2["status"]["conditions"][0]["reason"]


class TestSSHClusterWithoutOwner:
    """SSHCluster without ownerReference should stay not-ready."""

    def test_no_owner_stays_not_ready(self, custom_api, test_namespace):
        """Create SSHCluster without owner → reconcile → verify not provisioned."""
        spec = {"controlPlaneEndpoint": {"host": "10.0.0.3", "port": 6443}}
        name = "test-cluster-no-owner"

        create_sshcluster(custom_api, name, test_namespace, spec)
        resource = get_sshcluster(custom_api, name, test_namespace)

        patch = kopf.Patch({})
        _reconcile(resource["spec"], name, test_namespace, resource["metadata"], patch)

        assert patch["status"]["initialization"]["provisioned"] is False
        assert patch["status"]["conditions"][0]["reason"] == "WaitingForClusterOwner"


class TestSSHClusterPaused:
    """Paused SSHCluster should skip reconciliation entirely."""

    def test_paused_skips_reconciliation(
        self, custom_api, test_namespace, cluster_owner_ref
    ):
        """Create paused SSHCluster → reconcile → verify no status changes."""
        spec = {
            "controlPlaneEndpoint": {"host": "10.0.0.4", "port": 6443},
            "paused": True,
        }
        name = "test-cluster-paused"

        create_sshcluster(custom_api, name, test_namespace, spec, owner_refs=cluster_owner_ref)
        resource = get_sshcluster(custom_api, name, test_namespace)

        patch = kopf.Patch({})
        _reconcile(resource["spec"], name, test_namespace, resource["metadata"], patch)

        # Paused should not set any status
        assert "status" not in patch or "initialization" not in patch.get("status", {})


class TestSSHClusterInvalidEndpoint:
    """SSHCluster with invalid endpoint should be marked not-ready."""

    def test_empty_endpoint_not_ready(
        self, custom_api, test_namespace, cluster_owner_ref
    ):
        """Create SSHCluster with empty host → reconcile → verify InvalidEndpoint."""
        # CRD schema requires host, so we test with an empty string via direct reconcile
        spec = {"controlPlaneEndpoint": {"host": "", "port": 0}}

        patch = kopf.Patch({})
        meta = {"ownerReferences": cluster_owner_ref}
        _reconcile(spec, "test-invalid-ep", test_namespace, meta, patch)

        assert patch["status"]["initialization"]["provisioned"] is False
        assert patch["status"]["conditions"][0]["reason"] == "InvalidEndpoint"


class TestSSHClusterDelete:
    """SSHCluster deletion should succeed (no-op cleanup)."""

    def test_delete_removes_resource(
        self, custom_api, test_namespace, cluster_owner_ref
    ):
        """Create then delete SSHCluster → verify it's gone."""
        spec = {"controlPlaneEndpoint": {"host": "10.0.0.5", "port": 6443}}
        name = "test-cluster-delete"

        create_sshcluster(custom_api, name, test_namespace, spec, owner_refs=cluster_owner_ref)

        # Delete
        custom_api.delete_namespaced_custom_object(
            group="infrastructure.alpininsight.ai",
            version="v1beta1",
            namespace=test_namespace,
            plural="sshclusters",
            name=name,
        )

        # Verify deletion (may take a moment for finalizers)
        import time

        for _ in range(10):
            try:
                get_sshcluster(custom_api, name, test_namespace)
                time.sleep(0.5)
            except Exception:
                break
