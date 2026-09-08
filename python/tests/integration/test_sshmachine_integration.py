"""API storage/CAS tests complement the real kubeadm lifecycle lane (no fake persistence)."""

import kopf
import kubernetes
import pytest

from capi_provider_ssh.inventory import bind_machine
from tests.kind.runtime import SSH_GROUP, eventually

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]


def with_conflict_retry(action):
    def attempt():
        try:
            return action() or True
        except kopf.TemporaryError:
            return False
        except kubernetes.client.ApiException as exc:
            if exc.status != 409:
                raise
            return False

    return eventually("retry concurrent API updates", attempt, timeout=30)


def bind_current(rt):
    current = rt.get(SSH_GROUP, "sshmachines", "schema-only")
    return bind_machine(
        current["spec"],
        current.get("status", {}),
        "schema-only",
        rt.namespace,
        current["metadata"]["uid"],
        kopf.Patch(),
    )


@pytest.fixture
def machine(api_runtime):
    rt = api_runtime
    obj = rt.create(
        SSH_GROUP,
        "sshmachines",
        "SSHMachine",
        "schema-only",
        {
            "address": "192.0.2.10",
            "paused": True,
            "dryRun": True,
        },
    )
    yield obj
    # This object has no CAPI owner and never executed SSH. Remove synthetic
    # schema-test state before its ordinary (never-bootstrapped) deletion.
    rt.api.patch_namespaced_custom_object_status(
        SSH_GROUP,
        "v1beta1",
        rt.namespace,
        "sshmachines",
        "schema-only",
        {
            "status": {
                "bootstrapOwnership": None,
                "cleanup": None,
                "initialization": {"provisioned": False},
                "remediation": None,
            },
        },
    )
    rt.patch(SSH_GROUP, "sshmachines", "schema-only", {"spec": {"paused": False}})


def test_safety_state_roundtrips_only_via_status(api_runtime, machine):
    rt = api_runtime
    binding = {
        "machineUID": machine["metadata"]["uid"],
        "address": "192.0.2.10",
        "port": 2222,
        "user": "root",
        "sshHostKeyRef": {"name": "verified-hosts", "key": "known_hosts"},
    }
    state = {
        "allocation": binding,
        "bootstrapOwnership": {**binding, "startedAt": "2026-09-06T00:00:00Z"},
        "cleanup": {"phase": "Failed"},
        "remediation": {
            "reboot": {
                "phase": "Submitted",
                "success": False,
                "previousBootID": "00000000-0000-0000-0000-000000000001",
                "startedAt": "2026-09-06T00:00:00Z",
            }
        },
    }
    rt.patch(SSH_GROUP, "sshmachines", "schema-only", {"status": state})
    assert "allocation" not in rt.get(SSH_GROUP, "sshmachines", "schema-only").get("status", {})
    rt.api.patch_namespaced_custom_object_status(
        SSH_GROUP, "v1beta1", rt.namespace, "sshmachines", "schema-only", {"status": state}
    )
    result = rt.get(SSH_GROUP, "sshmachines", "schema-only")["status"]
    for key, expected in state.items():
        assert result[key] == expected


def test_host_claim_cas_rejects_a_stale_writer(api_runtime):
    rt = api_runtime
    host = rt.create(
        SSH_GROUP, "sshhosts", "SSHHost", "cas", {"address": "192.0.2.10", "sshKeyRef": {"name": "absent"}}
    )
    body = {
        "metadata": {"resourceVersion": host["metadata"]["resourceVersion"]},
        "spec": {"consumerRef": {"kind": "SSHMachine", "name": "a", "namespace": rt.namespace, "uid": "uid-a"}},
    }

    def claim():
        body["metadata"]["resourceVersion"] = rt.get(SSH_GROUP, "sshhosts", "cas")["metadata"]["resourceVersion"]
        return rt.patch(SSH_GROUP, "sshhosts", "cas", body)

    with_conflict_retry(claim)
    body["spec"]["consumerRef"]["uid"] = "uid-b"
    with pytest.raises(kubernetes.client.ApiException) as error:
        rt.patch(SSH_GROUP, "sshhosts", "cas", body)
    assert error.value.status == 409
    rt.patch(SSH_GROUP, "sshhosts", "cas", {"spec": {"consumerRef": None}})


def test_pool_binding_preserves_port_and_claim_when_health_changes(api_runtime, machine):
    rt = api_runtime
    rt.create(
        SSH_GROUP,
        "sshhosts",
        "SSHHost",
        "pool",
        {
            "address": "192.0.2.11",
            "port": 2222,
            "sshKeyRef": {"name": "absent"},
            "sshHostKeyRef": {"name": "verified-hosts", "key": "known_hosts"},
        },
        metadata={"labels": {"test-pool": "yes"}},
    )
    rt.api.patch_namespaced_custom_object_status(
        SSH_GROUP, "v1beta1", rt.namespace, "sshhosts", "pool", {"status": {"ready": True}}
    )
    rt.patch(SSH_GROUP, "sshmachines", "schema-only", {"spec": {"hostSelector": {"matchLabels": {"test-pool": "yes"}}}})
    current = rt.get(SSH_GROUP, "sshmachines", "schema-only")
    with_conflict_retry(lambda: bind_current(rt))
    rt.api.patch_namespaced_custom_object_status(
        SSH_GROUP, "v1beta1", rt.namespace, "sshhosts", "pool", {"status": {"ready": False}}
    )
    rt.patch(SSH_GROUP, "sshhosts", "pool", {"metadata": {"labels": {"test-pool": None}}})
    current = rt.get(SSH_GROUP, "sshmachines", "schema-only")
    binding = with_conflict_retry(lambda: bind_current(rt))
    assert binding["port"] == 2222 and current["spec"]["port"] == 2222
    assert rt.get(SSH_GROUP, "sshhosts", "pool")["status"]["inUse"] is True
    # No SSH was performed; release this synthetic allocation through the contract.
    from capi_provider_ssh.inventory import release_host

    release_host(binding, "schema-only", rt.namespace, current["metadata"]["uid"])
