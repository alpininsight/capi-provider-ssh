"""API failure and stale HA state must not be reported as controller readiness."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock

import kubernetes
import pytest
import yaml

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.main import runtime_probe
from capi_provider_ssh.readiness import NotReadyError, check_readiness, local_runtime, main

NOW = datetime(2026, 9, 6, 21, tzinfo=UTC)


@pytest.fixture
def runtime():
    return {"configured": True, "ha": True, "priority": 123, "started_at": (NOW - timedelta(seconds=20)).isoformat()}


@pytest.fixture
def api():
    client = Mock()
    client.get_cluster_custom_object.return_value = {
        "status": {
            "this-process": {"priority": 123, "lastseen": (NOW - timedelta(seconds=2)).isoformat(), "lifetime": 30}
        }
    }
    return client


def test_active_and_standby_with_fresh_own_heartbeat_are_ready(api, runtime):
    api.get_cluster_custom_object.return_value["status"]["higher-priority"] = {
        "priority": 456,
        "lastseen": NOW.isoformat(),
        "lifetime": 30,
    }
    check_readiness(api, runtime, now=NOW)
    api.list_cluster_custom_object.assert_called_once_with(
        API_GROUP, API_VERSION, "sshclusters", limit=1, _request_timeout=(1, 2)
    )
    api.get_cluster_custom_object.assert_called_once_with(
        "kopf.dev", "v1", "clusterkopfpeerings", "capi-provider-ssh", _request_timeout=(1, 2)
    )


@pytest.mark.parametrize(
    "status", [None, {}, {"other-pod": {"priority": 456, "lastseen": NOW.isoformat(), "lifetime": 30}}]
)
def test_healthy_other_replica_cannot_make_this_replica_ready(api, runtime, status):
    api.get_cluster_custom_object.return_value = {"status": status}
    with pytest.raises(NotReadyError, match="no fresh peering heartbeat"):
        check_readiness(api, runtime, now=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"lastseen": (NOW - timedelta(seconds=31)).isoformat()},
        {"lastseen": (NOW - timedelta(seconds=21)).isoformat()},
        {"lastseen": (NOW + timedelta(seconds=1)).isoformat()},
        {"lastseen": NOW.replace(tzinfo=None).isoformat()},
        {"lastseen": "invalid"},
        {"lifetime": 0},
        {"lifetime": "invalid"},
        {"lifetime": float("nan")},
        {"lastseen": (NOW - timedelta(seconds=31)).isoformat(), "lifetime": 9999},
    ],
)
def test_stale_prior_process_and_malformed_heartbeats_fail_closed(api, runtime, change):
    api.get_cluster_custom_object.return_value["status"]["this-process"].update(change)
    with pytest.raises(NotReadyError, match="no fresh peering heartbeat"):
        check_readiness(api, runtime, now=NOW)


@pytest.mark.parametrize(
    "field,value", [("configured", False), ("priority", None), ("priority", True), ("started_at", "")]
)
def test_incomplete_startup_is_not_ready(api, runtime, field, value):
    runtime[field] = value
    with pytest.raises(NotReadyError):
        check_readiness(api, runtime, now=NOW)


@pytest.mark.parametrize("status", [401, 403, 404, 503])
@pytest.mark.parametrize("operation", ["list_cluster_custom_object", "get_cluster_custom_object"])
def test_api_authentication_authorization_and_availability_are_required(api, runtime, status, operation):
    getattr(api, operation).side_effect = kubernetes.client.ApiException(status=status)
    with pytest.raises(kubernetes.client.ApiException):
        check_readiness(api, runtime, now=NOW)


def test_explicit_non_ha_mode_still_requires_authenticated_crd_access(api, runtime):
    runtime["ha"] = False
    check_readiness(api, runtime, now=NOW)
    api.list_cluster_custom_object.assert_called_once()
    api.get_cluster_custom_object.assert_not_called()


@pytest.mark.parametrize("payload,status", [({}, 200), ({"runtime": {"configured": False}}, 200), ({}, 503)])
def test_liveness_alone_is_not_readiness(monkeypatch, payload, status):
    connection = Mock()
    connection.getresponse.return_value.status = status
    connection.getresponse.return_value.read.return_value = json.dumps(payload).encode()
    factory = Mock(return_value=connection)
    monkeypatch.setattr("http.client.HTTPConnection", factory)
    with pytest.raises(NotReadyError):
        local_runtime()
    factory.assert_called_once_with("127.0.0.1", 8080, timeout=1)
    connection.close.assert_called_once()


def test_local_liveness_has_no_dependency_on_upstream_api(monkeypatch):
    monkeypatch.setattr(
        "kubernetes.client.CustomObjectsApi", Mock(side_effect=AssertionError("API must not be called"))
    )
    assert isinstance(runtime_probe(), dict)


def test_probe_process_disables_retries_and_closes_client(monkeypatch, runtime):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.setattr("capi_provider_ssh.readiness.local_runtime", lambda: runtime)
    load = Mock()
    monkeypatch.setattr("capi_provider_ssh.readiness.load_api_config", load)
    factory = MagicMock()
    monkeypatch.setattr("kubernetes.client.ApiClient", factory)
    api_factory = Mock()
    monkeypatch.setattr("kubernetes.client.CustomObjectsApi", api_factory)
    check = Mock()
    monkeypatch.setattr("capi_provider_ssh.readiness.check_readiness", check)
    assert main() == 0
    load.assert_called_once()
    assert factory.call_args.args[0].retries == 0
    factory.return_value.__exit__.assert_called_once()
    check.assert_called_once_with(api_factory.return_value, runtime)


def test_probe_errors_never_log_credentials_or_raw_api_payload(monkeypatch, capsys):
    monkeypatch.setattr(
        "capi_provider_ssh.readiness.local_runtime",
        Mock(side_effect=RuntimeError("Authorization: Bearer do-not-print-this")),
    )
    assert main() == 1
    assert capsys.readouterr().out == "not ready: RuntimeError\n"


def test_deployment_separates_liveness_from_api_readiness():
    from pathlib import Path

    deploy = Path(__file__).resolve().parents[1] / "deploy/deployment.yaml"
    container = yaml.safe_load(deploy.read_text())["spec"]["template"]["spec"]["containers"][0]
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["readinessProbe"]["exec"]["command"] == ["python", "-B", "-m", "capi_provider_ssh.readiness"]
    assert container["readinessProbe"]["timeoutSeconds"] >= 10
    assert "exec" not in container["livenessProbe"]
    assert container["resources"]["requests"]["memory"] == "128Mi"
    assert container["resources"]["limits"]["memory"] == "512Mi"
