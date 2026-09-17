"""Pure diagnostic projections and fake-client checks, not a real Kind replay."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import kubernetes
import pytest

from tests.kind import diagnostics
from tests.kind.runtime import Runtime, eventually, referenced_machine_conditions_current

NAMESPACE = "test-capi-ssh-life-example"
UID = "6402fe94-15c7-468c-a44d-f677c6abd6e0"
OWNER_UID = "720bc889-c625-43ba-9a01-3d26387e94c1"


@pytest.fixture
def machine():
    return {
        "kind": "SSHMachine",
        "metadata": {
            "name": "workers-example",
            "namespace": NAMESPACE,
            "uid": UID,
            "generation": 1,
            "resourceVersion": "6299",
            "ownerReferences": [{"kind": "MachineSet", "name": "workers", "uid": OWNER_UID}],
            "managedFields": [{"manager": "capi-machineset", "operation": "Apply"}],
        },
        "status": {
            "ready": False,
            "initialization": {"provisioned": False},
            "conditions": [
                {
                    "type": "Ready",
                    "status": "False",
                    "observedGeneration": 1,
                    "reason": "WaitingForMachineOwner",
                }
            ],
        },
    }


def test_resource_projects_generation_ownership_and_nonprovisioning(machine):
    result = diagnostics.resource(machine)
    assert result["generation"] == 1
    assert result["resourceVersion"] == "6299"
    assert result["uid"] == UID
    assert result["ownerReferences"] == [{"kind": "MachineSet", "name": "workers", "uid": OWNER_UID}]
    assert result["managedFields"] == [{"manager": "capi-machineset", "operation": "Apply", "subresource": "Other"}]
    assert result["status"] == {
        "ready": False,
        "provisioned": False,
        "v1beta2Conditions": [],
        "conditions": [
            {
                "type": "Ready",
                "status": "False",
                "reason": "WaitingForMachineOwner",
                "observedGeneration": 1,
                "errorClasses": [],
            }
        ],
    }


def test_machine_ref_and_machineset_status_are_projected(machine):
    value = copy.deepcopy(machine)
    value["kind"] = "Machine"
    value["spec"] = {"infrastructureRef": {"kind": "SSHMachine", "name": "workers-example", "uid": UID}}
    assert diagnostics.resource(value)["infrastructureRef"] == value["spec"]["infrastructureRef"]
    value["kind"] = "MachineSet"
    value["status"] = {
        "observedGeneration": 2,
        "replicas": 1,
        "readyReplicas": 0,
        "v1beta2": {"conditions": [{"type": "ScalingUp", "status": "True", "reason": "InternalError"}]},
    }
    result = diagnostics.resource(value)
    assert result["status"]["replicas"] == 1
    assert result["status"]["readyReplicas"] == 0
    assert result["status"]["observedGeneration"] == 2
    assert result["status"]["v1beta2Conditions"][0]["reason"] == "InternalError"
    assert "infrastructureRef" not in result


@pytest.mark.parametrize(
    "payload",
    [
        "abcdef.0123456789abcdef",
        "Secretdata-unknown-content",
        "Arbitrarymessage-unknown-content",
        "kubeadm join 192.0.2.1 --token abcdef.0123456789abcdef",
        "Authorization: Bearer unknown-credential",
    ],
)
def test_unallowlisted_payload_never_enters_any_projection(machine, payload):
    machine["spec"] = {"bootstrap": {"dataSecretName": payload}, "environment": payload, "kubeconfig": payload}
    machine["data"] = {"token": payload}
    machine["metadata"].update(annotations={"payload": payload}, labels={"payload": payload})
    machine["metadata"]["managedFields"].append({"manager": payload, "operation": payload, "fieldsV1": payload})
    machine["metadata"]["ownerReferences"].append({"kind": "Secret", "name": payload})
    machine["status"]["conditions"].append({"type": payload, "status": payload, "reason": payload, "message": payload})
    projected = diagnostics.resource(machine)
    ref = {"kind": "SSHMachine", "name": "workers-example", "namespace": NAMESPACE, "uid": UID}
    entry = {"involvedObject": ref, "type": "Warning", "reason": payload, "message": payload, "action": payload}
    text = f'SSHMachine="{NAMESPACE}/workers-example" failed to create InfraMachine: {payload}'
    output = json.dumps(
        [projected, diagnostics.event(entry, NAMESPACE), diagnostics.controller_errors(text, [projected])]
    )
    assert payload not in output
    assert "InfraMachineCreateFailed" in output
    assert "fieldsV1" not in output
    assert "annotations" not in output
    assert "spec" not in projected
    assert "data" not in projected


def test_events_and_controller_errors_export_only_known_classes_and_refs(machine):
    entry = {
        "involvedObject": {"kind": "MachineSet", "name": "workers", "namespace": NAMESPACE, "uid": OWNER_UID},
        "type": "Warning",
        "reason": "FailedCreate",
        "count": 2,
        "message": "failed to clone infrastructure machine: the object has been modified; arbitrary private detail",
    }
    assert diagnostics.event(entry, NAMESPACE) == {
        "object": entry["involvedObject"],
        "type": "Warning",
        "reason": "FailedCreate",
        "count": 2,
        "errorClasses": ["InfrastructureCloneFailed", "OptimisticLockConflict"],
    }
    projected = diagnostics.resource(machine)
    text = f'SSHMachine="{NAMESPACE}/workers-example" failed to create InfraMachine: the object has been modified'
    result = diagnostics.controller_errors(text + "\n" + text, [projected])
    assert {item["errorClass"] for item in result} == {"InfraMachineCreateFailed", "OptimisticLockConflict"}
    assert all(item["count"] == 2 and item["objectAtSnapshot"]["uid"] == UID for item in result)
    assert diagnostics.controller_errors(text.replace(NAMESPACE, "another-namespace"), [projected]) == []
    assert diagnostics.controller_errors(text.replace("workers-example", "workers-example-other"), [projected]) == []
    assert diagnostics.controller_errors("unknown log format or error", [projected]) == []
    entry["involvedObject"]["kind"] = "Secret"
    assert diagnostics.event(entry, NAMESPACE) is None


def test_capi_11211_managed_fields_error_chain_keeps_class_not_free_text():
    # Source-shaped fixture from v1.12.11 internal/util/ssa/managedfields.go:127,
    # wrapped by createInfraMachine/createMachines; not a log observed in the failed CI run.
    managed_fields = (
        f"failed to remove managedFields for labels and annotations from SSHMachine {NAMESPACE}/workers-example"
    )
    assert diagnostics.error_classes(managed_fields) == ["ManagedFieldsCleanupFailed"]
    chain = (
        "failed to clone infrastructure machine from SSHMachineTemplate workers while creating a Machine: "
        f"failed to create InfraMachine: {managed_fields}: "
        'Operation cannot be fulfilled on sshmachines.infrastructure.alpininsight.ai "workers-example": '
        "the object has been modified; please apply your changes to the latest version and try again"
    )
    ref = {"kind": "MachineSet", "name": "workers", "namespace": NAMESPACE, "uid": OWNER_UID}
    line = f'Reconciler error MachineSet="{NAMESPACE}/workers" err="{chain}" Authorization: Bearer private-token'
    result = diagnostics.controller_errors(line, [ref])
    assert result == [
        {"objectAtSnapshot": ref, "errorClass": code, "count": 1}
        for code in (
            "InfraMachineCreateFailed",
            "InfrastructureCloneFailed",
            "ManagedFieldsCleanupFailed",
            "OptimisticLockConflict",
        )
    ]
    output = json.dumps(result)
    assert chain not in output
    assert managed_fields not in output
    assert "private-token" not in output
    assert "Authorization" not in output


@pytest.fixture
def runtime(machine):
    rt = object.__new__(Runtime)
    rt.namespace = NAMESPACE
    rt.api = Mock()
    rt.api.list_namespaced_custom_object.return_value = {"items": [machine]}
    rt.core = Mock()
    rt.core.api_client.sanitize_for_serialization.side_effect = lambda value: value
    rt.core.list_namespaced_event.return_value = {"items": []}
    rt.core.list_namespaced_pod.return_value = {
        "items": [
            {
                "metadata": {
                    "name": "capi-controller-manager-example",
                    "namespace": "capi-system",
                    "uid": OWNER_UID,
                }
            }
        ]
    }
    rt.core.read_namespaced_pod_log.return_value = "unknown private log content"
    return rt


def test_collector_uses_only_bounded_read_apis_and_reports_missing_evidence(runtime):
    result = runtime.lifecycle_diagnostics()
    assert result["snapshotComplete"] is True
    assert len(result["resources"]) == 4
    assert "unknown private log content" not in json.dumps(result)
    assert {call.args[3] for call in runtime.api.list_namespaced_custom_object.call_args_list} == {
        "sshmachines",
        "machines",
        "machinesets",
        "machinedeployments",
    }
    for call in runtime.api.list_namespaced_custom_object.call_args_list:
        assert call.args[2] == NAMESPACE
        assert call.kwargs == {"limit": 100, "_request_timeout": (3, 10)}
    runtime.core.read_namespaced_pod_log.assert_called_once_with(
        "capi-controller-manager-example",
        "capi-system",
        container="manager",
        tail_lines=500,
        limit_bytes=65536,
        _request_timeout=(3, 10),
    )
    runtime.core.list_namespaced_event.return_value = {"items": [], "metadata": {"continue": "private-cursor"}}
    runtime.core.list_namespaced_pod.return_value = {"items": []}
    result = runtime.lifecycle_diagnostics()
    assert result["snapshotComplete"] is False
    assert result["collectionErrors"] == [
        {"source": "events", "errorClass": "ListTruncated"},
        {"source": "capiControllerPods", "errorClass": "NoControllerPods"},
    ]
    assert "private-cursor" not in json.dumps(result)


def test_collection_failure_exports_no_exception_body_and_is_not_complete(runtime):
    error = kubernetes.client.exceptions.ApiException(status=403, reason="Authorization: Bearer private-token")
    error.body = "Secret data bootstrap-command"
    runtime.api.list_namespaced_custom_object.side_effect = error
    result = runtime.lifecycle_diagnostics()
    assert result["snapshotComplete"] is False
    assert len(result["collectionErrors"]) == 4
    assert all(item["httpStatus"] == 403 for item in result["collectionErrors"])
    assert "private-token" not in json.dumps(result)
    assert "bootstrap-command" not in json.dumps(result)


def test_malformed_projection_does_not_interrupt_cleanup_or_export_response(runtime):
    runtime.api.list_namespaced_custom_object.return_value = {"items": [{"metadata": "private-bootstrap-payload"}]}
    assert runtime.lifecycle_diagnostics() == {
        "snapshotComplete": False,
        "collectionErrors": [{"source": "projection", "errorClass": "DiagnosticCollectionFailed"}],
    }


def test_eventually_retains_timing_and_only_diagnoses_a_failed_assertion(monkeypatch):
    clock = Mock(side_effect=[0, 0, 179, 180])
    sleep = Mock()
    monkeypatch.setattr("tests.kind.runtime.time", SimpleNamespace(monotonic=clock, sleep=sleep))
    check = Mock(return_value=False)
    diagnose = Mock(return_value={"resources": [{"generation": 1, "status": {"ready": False}}]})
    with pytest.raises(AssertionError, match="Timed out: unchanged contract") as failure:
        eventually("unchanged contract", check, diagnose=diagnose)
    assert check.call_count == 2
    assert sleep.call_args_list == [((2,),), ((2,),)]
    diagnose.assert_called_once_with()
    assert json.loads(str(failure.value).split("\n", 1)[1]) == diagnose.return_value
    clock.side_effect = [0, 0]
    diagnose.reset_mock()
    assert eventually("unchanged contract", lambda: True, diagnose=diagnose) is True
    diagnose.assert_not_called()


def test_failed_diagnostic_cannot_hide_timeout_or_leak_exception(monkeypatch):
    monkeypatch.setattr("tests.kind.runtime.time.monotonic", Mock(side_effect=[0, 180]))
    diagnose = Mock(side_effect=ValueError("Authorization: Bearer private-token"))
    with pytest.raises(AssertionError, match="Timed out: unchanged contract") as failure:
        eventually("unchanged contract", lambda: False, diagnose=diagnose)
    assert "DiagnosticCollectionFailed" in str(failure.value)
    assert "private-token" not in str(failure.value)


def test_condition_generation_check_uses_capi_references_not_unadopted_clones(machine):
    machine["metadata"]["ownerReferences"] = [{"kind": "Machine", "uid": OWNER_UID}]
    machine["status"]["conditions"] = [
        {"type": "Ready", "status": "True", "observedGeneration": 1},
        {"type": "Paused", "status": "False"},
    ]
    capi_machines = [
        {
            "metadata": {"uid": OWNER_UID},
            "spec": {"infrastructureRef": {"kind": "SSHMachine", "name": "workers-example"}},
        }
    ]
    clone = copy.deepcopy(machine)
    clone["metadata"]["name"] = "workers-unadopted"
    clone["metadata"]["ownerReferences"] = [{"kind": "MachineSet", "uid": OWNER_UID}]
    clone["status"]["conditions"][0]["status"] = "False"
    assert referenced_machine_conditions_current(capi_machines, [machine, clone], expected_count=1)

    machine["status"]["conditions"][0]["observedGeneration"] = 0
    assert not referenced_machine_conditions_current(capi_machines, [machine, clone], expected_count=1)
