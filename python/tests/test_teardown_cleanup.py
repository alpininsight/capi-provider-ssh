"""Unit tests for integration teardown contract helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import kubernetes
import pytest

from tests.integration.cleanup import (
    TeardownConfig,
    _clear_stuck_finalizers,
    collect_namespace_residue,
    is_test_namespace,
    teardown_test_namespace,
)


def _api_error(status: int) -> kubernetes.client.ApiException:
    return kubernetes.client.ApiException(status=status, reason=f"status-{status}")


def _namespace(name: str, labels: dict[str, str] | None):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels=labels,
            finalizers=[],
            deletion_timestamp=None,
        ),
        status=SimpleNamespace(phase="Active"),
    )


def test_is_test_namespace_requires_prefix_and_label() -> None:
    assert is_test_namespace("test-capi-ssh-abc123", {"capi-provider-ssh-test": "true"}) is True
    assert is_test_namespace("default", {"capi-provider-ssh-test": "true"}) is False
    assert is_test_namespace("test-capi-ssh-abc123", {"capi-provider-ssh-test": "false"}) is False
    assert is_test_namespace("test-capi-ssh-abc123", None) is False


def test_teardown_rejects_non_test_namespace() -> None:
    core_api = MagicMock()
    custom_api = MagicMock()
    core_api.read_namespace.return_value = _namespace("default", {"capi-provider-ssh-test": "true"})

    with pytest.raises(ValueError, match="Refusing teardown for non-test namespace"):
        teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace="default")


def test_teardown_is_noop_when_namespace_already_deleted() -> None:
    core_api = MagicMock()
    custom_api = MagicMock()
    core_api.read_namespace.side_effect = _api_error(404)

    report = teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace="test-capi-ssh-deadbeef")
    assert report.namespace == "test-capi-ssh-deadbeef"
    assert report.deleted_resources == {}
    assert report.remediated_finalizers == 0


def test_clear_stuck_finalizers_patches_only_deleting_objects() -> None:
    custom_api = MagicMock()
    custom_api.list_namespaced_custom_object.return_value = {
        "items": [
            {
                "metadata": {
                    "name": "stuck",
                    "deletionTimestamp": "2026-02-23T23:00:00Z",
                    "finalizers": ["machine.cluster.x-k8s.io"],
                }
            },
            {
                "metadata": {
                    "name": "healthy",
                    "finalizers": [],
                }
            },
        ]
    }

    patched = _clear_stuck_finalizers(
        custom_api=custom_api,
        namespace="test-capi-ssh-abc123",
        group="cluster.x-k8s.io",
        version="v1beta1",
        plural="machines",
    )

    assert patched == 1
    custom_api.patch_namespaced_custom_object.assert_called_once()
    patch_body = custom_api.patch_namespaced_custom_object.call_args.kwargs["body"]
    assert patch_body["metadata"]["finalizers"] == []


def test_collect_namespace_residue_filters_test_secrets() -> None:
    core_api = MagicMock()
    custom_api = MagicMock()
    core_api.read_namespace.return_value = _namespace("test-capi-ssh-abc123", {"capi-provider-ssh-test": "true"})
    core_api.list_namespaced_secret.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(metadata=SimpleNamespace(name="test-bootstrap-data")),
            SimpleNamespace(metadata=SimpleNamespace(name="business-secret")),
        ]
    )
    custom_api.list_namespaced_custom_object.return_value = {"items": []}

    residue = collect_namespace_residue(
        core_api=core_api,
        custom_api=custom_api,
        namespace="test-capi-ssh-abc123",
    )

    assert residue["namespace"] == ["test-capi-ssh-abc123"]
    assert residue["secrets"] == ["test-bootstrap-data"]


def test_teardown_collects_debug_bundle_on_failure(tmp_path) -> None:
    core_api = MagicMock()
    custom_api = MagicMock()
    core_api.read_namespace.return_value = _namespace("test-capi-ssh-abc123", {"capi-provider-ssh-test": "true"})
    core_api.list_namespaced_secret.return_value = SimpleNamespace(items=[])

    custom_api.list_namespaced_custom_object.side_effect = [
        {"items": [{"metadata": {"name": "obj1"}}]},  # sshmachines list (delete pass)
        {"items": []},  # sshclusters list
        {"items": []},  # machines list
        {"items": []},  # kubeadmconfigs list
        {"items": []},  # residue sshmachines
        {"items": []},  # residue sshclusters
        {"items": []},  # residue machines
        {"items": []},  # residue kubeadmconfigs
        {"items": []},  # bundle sshmachines
        {"items": []},  # bundle sshclusters
        {"items": []},  # bundle machines
        {"items": []},  # bundle kubeadmconfigs
    ]
    custom_api.delete_namespaced_custom_object.side_effect = RuntimeError("delete failed")

    with pytest.raises(RuntimeError, match="delete failed"):
        teardown_test_namespace(
            core_api=core_api,
            custom_api=custom_api,
            namespace="test-capi-ssh-abc123",
            config=TeardownConfig(artifact_dir=tmp_path),
        )

    bundles = list(tmp_path.glob("test-capi-ssh-abc123-*"))
    assert bundles, "expected teardown debug bundle directory to be created"
    residue_files = list(bundles[0].glob("residue.json"))
    assert residue_files, "expected residue.json in teardown debug bundle"


def test_teardown_prefers_machine_delete_before_sshmachine() -> None:
    core_api = MagicMock()
    custom_api = MagicMock()
    core_api.read_namespace.side_effect = [
        _namespace("test-capi-ssh-abc123", {"capi-provider-ssh-test": "true"}),
        _api_error(404),
        _api_error(404),
    ]
    core_api.list_namespaced_secret.return_value = SimpleNamespace(items=[])
    custom_api.list_namespaced_custom_object.return_value = {"items": []}

    teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace="test-capi-ssh-abc123")

    plural_calls = [call.kwargs.get("plural") for call in custom_api.list_namespaced_custom_object.call_args_list[:4]]
    assert plural_calls == ["machines", "sshmachines", "sshclusters", "kubeadmconfigs"]
