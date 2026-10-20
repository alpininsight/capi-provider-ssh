"""Keep CAPI owner identity distinct from foreign groups and URL substrings."""

import pytest

from capi_provider_ssh import contracts
from capi_provider_ssh.controllers.sshcluster import _has_capi_cluster_owner
from capi_provider_ssh.controllers.sshmachine import _get_machine_owner_ref, _has_machine_owner


@pytest.mark.parametrize(
    "api_version",
    [
        None,
        1,
        {},
        "",
        "cluster.x-k8s.io",
        "cluster.x-k8s.io/",
        "cluster.x-k8s.io/v1beta1/extra",
        "cluster.x-k8s.io.evil/v1beta1",
        "evil.cluster.x-k8s.io/v1beta1",
        "https://cluster.x-k8s.io/v1beta1",
        "Cluster.x-k8s.io/v1beta1",
        "infrastructure.cluster.x-k8s.io/v1beta1",
    ],
    ids=[
        "null",
        "number",
        "object",
        "empty",
        "no-version",
        "empty-version",
        "extra-path",
        "suffix-group",
        "prefix-group",
        "url",
        "case",
        "infrastructure-group",
    ],
)
def test_foreign_or_malformed_owner_never_establishes_capi_identity(api_version, monkeypatch):
    owner = {"apiVersion": api_version, "kind": "Machine", "name": "machine"}

    def unexpected_read(*args, **kwargs):
        pytest.fail("Foreign or malformed owner must not be used for a CAPI API read")

    monkeypatch.setattr(contracts, "get_object", unexpected_read)
    assert contracts.capi_owner_api_version(owner) is None
    assert not _has_machine_owner([owner])
    assert _get_machine_owner_ref([owner]) is None
    assert not _has_capi_cluster_owner([{**owner, "kind": "Cluster"}])
    assert not contracts.is_paused({}, {"ownerReferences": [owner]}, "test")


@pytest.mark.parametrize("version", ["v1beta1", "v1beta2"])
def test_valid_owner_keeps_version_and_pause_lookup(version, monkeypatch):
    owner = {"apiVersion": f"cluster.x-k8s.io/{version}", "kind": "Machine", "name": "machine", "uid": "uid"}
    reads = []

    def get_object(plural, namespace, name, *, group, version):
        reads.append((group, version, plural, namespace, name))
        return {"metadata": {"uid": "uid"}, "spec": {"paused": True}}

    monkeypatch.setattr(contracts, "get_object", get_object)
    assert contracts.capi_owner_api_version(owner) == version
    assert _has_machine_owner([owner])
    assert _get_machine_owner_ref([owner]) is owner
    assert _has_capi_cluster_owner([{**owner, "kind": "Cluster"}])
    assert contracts.is_paused({}, {"ownerReferences": [owner]}, "test")
    assert reads == [("cluster.x-k8s.io", version, "machines", "test", "machine")]
    assert not _has_machine_owner([{**owner, "kind": "Secret"}])
    assert not _has_capi_cluster_owner([{**owner, "kind": "Machine"}])


def test_empty_owner_list_does_not_establish_ownership():
    assert contracts.capi_owner_api_version({}) is None
    for refs in (None, []):
        assert not _has_machine_owner(refs)
        assert _get_machine_owner_ref(refs) is None
        assert not _has_capi_cluster_owner(refs)
