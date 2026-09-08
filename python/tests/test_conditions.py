"""Condition ownership, status transitions and observation freshness."""

from copy import deepcopy

import kopf
import pytest

from capi_provider_ssh.conditions import condition, merge_conditions, patch_conditions, report_pause

OLD = "2026-09-01T00:00:00+00:00"


def test_reason_and_generation_updates_preserve_status_transition_and_other_writers():
    existing = [
        {**condition("Ready", "False", "Waiting", "Old reason"), "lastTransitionTime": OLD, "observedGeneration": 1},
        {**condition("ConsumerHealthy", "True", "Healthy", "Other controller"), "lastTransitionTime": OLD},
    ]
    before = deepcopy(existing)
    result = merge_conditions(existing, [condition("Ready", "False", "CleanupFailed", "Retry needed")], 2)
    assert existing == before
    assert result[0]["reason"] == "CleanupFailed"
    assert result[0]["observedGeneration"] == 2
    assert result[0]["lastTransitionTime"] == OLD
    assert result[1] == before[1]
    transitioned = merge_conditions(result, [condition("Ready", "True", "Provisioned", "Ready")], 3)
    assert transitioned[0]["lastTransitionTime"] != OLD


def test_multiple_patch_updates_preserve_staged_and_persisted_conditions():
    status = {"conditions": [condition("External", "True", "Healthy", "External")]}
    patch = kopf.Patch()
    patch_conditions(patch, status, {"generation": 2}, [condition("Ready", "False", "Waiting", "Waiting")])
    patch_conditions(patch, status, {"generation": 2}, [condition("Paused", "True", "Paused", "Paused")])
    assert {item["type"] for item in patch.status["conditions"]} == {"Ready", "Paused", "External"}


def test_failed_pause_check_reports_unknown_without_changing_readiness():
    status = {
        "ready": True,
        "conditions": [{**condition("Ready", "True", "Provisioned", "Ready"), "observedGeneration": 1}],
    }
    patch = kopf.Patch()

    def unavailable():
        raise kopf.TemporaryError("API unavailable")

    with pytest.raises(kopf.TemporaryError, match="unavailable"):
        report_pause(patch, status, {"generation": 2}, unavailable)
    values = {item["type"]: item for item in patch.status["conditions"]}
    assert "ready" not in patch.status
    assert values["Ready"] == status["conditions"][0]
    assert values["Paused"]["status"] == "Unknown"
    assert values["Paused"]["observedGeneration"] == 2
