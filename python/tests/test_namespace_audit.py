"""Audit candidates require owner label, prefix, terminating state and actual age."""

import copy
import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from capi_provider_ssh.namespace_audit import audit, is_stuck_test

NOW = datetime.datetime(2026, 9, 6, 12, tzinfo=datetime.UTC)
CANDIDATE = {
    "metadata": {
        "name": "test-capi-ssh-example",
        "labels": {"capi-provider-ssh-test": "true"},
        "deletionTimestamp": "2026-09-06T10:59:59Z",
    },
    "status": {"phase": "Terminating"},
}


@pytest.mark.parametrize("age,expected", [(3599, False), (3600, True), (7200, True), (-10, False)])
def test_age_boundary(age, expected):
    obj = copy.deepcopy(CANDIDATE)
    obj["metadata"]["deletionTimestamp"] = (NOW - datetime.timedelta(seconds=age)).isoformat()
    assert is_stuck_test(obj, NOW) is expected


@pytest.mark.parametrize(
    "mutation",
    [
        {"name": "production"},
        {"labels": {}},
        {"labels": {"capi-provider-ssh-test": "false"}},
        {"deletionTimestamp": None},
        {"deletionTimestamp": "invalid"},
        {"deletionTimestamp": "2026-09-06T10:59:59"},
    ],
)
def test_unowned_or_unverifiable_namespace_is_ignored(mutation):
    obj = copy.deepcopy(CANDIDATE)
    obj["metadata"].update(mutation)
    assert not is_stuck_test(obj, NOW)


def test_active_namespace_is_ignored():
    obj = copy.deepcopy(CANDIDATE)
    obj["status"]["phase"] = "Active"
    assert not is_stuck_test(obj, NOW)


def test_audit_only_reads_and_reports_finalizers():
    core, custom = Mock(), Mock()
    core.list_namespace.return_value = SimpleNamespace(items=[CANDIDATE])
    custom.list_namespaced_custom_object.return_value = {
        "items": [
            {
                "kind": "SSHMachine",
                "metadata": {"name": "failed", "uid": "uid", "finalizers": ["cleanup"]},
                "spec": {"private": "never report arbitrary payloads"},
                "status": {"cleanup": {"phase": "Failed"}},
            }
        ]
    }
    result = audit(core, custom, now=NOW)
    assert result[0]["resources"][0]["finalizers"] == ["cleanup"]
    assert "private" not in str(result)
    assert [call[0] for call in core.mock_calls] == ["list_namespace"]
    assert [call[0] for call in custom.mock_calls] == ["list_namespaced_custom_object"] * 2
