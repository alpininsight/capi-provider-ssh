"""Bounded, authenticated readiness checks, separate from Kopf's liveness server."""

from __future__ import annotations

import http.client
import json
import os
from datetime import UTC, datetime

import kubernetes

from capi_provider_ssh import API_GROUP, API_VERSION

PEERING_NAME = "capi-provider-ssh"
PEERING_LIFETIME = 30
REQUEST_TIMEOUT = (1, 2)


class NotReadyError(Exception):
    """A safe diagnostic that contains no API response or credential material."""


def load_api_config() -> None:
    """Use the pod's rotating credentials or an explicitly selected local context."""
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        kubernetes.config.load_incluster_config()
    elif os.environ.get("KUBECONFIG"):
        kubernetes.config.load_kube_config(config_file=os.environ["KUBECONFIG"])
    else:
        raise RuntimeError("Set KUBECONFIG explicitly for local execution, or run with in-cluster credentials")


def local_runtime() -> dict:
    """Read this process's startup epoch; a previous container's peer is insufficient."""
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=1)
    try:
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        if response.status != 200:
            raise NotReadyError("local liveness is unavailable")
        payload = json.loads(response.read(65536))
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("configured") is not True:
            raise NotReadyError("operator startup has not completed")
        return runtime
    finally:
        connection.close()


def check_readiness(api, runtime: dict, *, now: datetime | None = None) -> None:
    """Require CRD access and this process's fresh peer, including on the standby.

    This checks API/coordination readiness, not the success of every individual
    resource handler. It never changes API objects or selects an active replica.
    """
    if runtime.get("configured") is not True:
        raise NotReadyError("operator startup has not completed")
    api.list_cluster_custom_object(API_GROUP, API_VERSION, "sshclusters", limit=1, _request_timeout=REQUEST_TIMEOUT)
    if runtime.get("ha") is False:
        return
    priority = runtime.get("priority")
    if type(priority) is not int:
        raise NotReadyError("operator peering identity is unavailable")
    try:
        started_at = datetime.fromisoformat(runtime["started_at"])
        if started_at.tzinfo is None:
            raise ValueError("timezone missing")
    except (KeyError, TypeError, ValueError) as exc:
        raise NotReadyError("operator startup epoch is unavailable") from exc
    peering = api.get_cluster_custom_object(
        "kopf.dev", "v1", "clusterkopfpeerings", PEERING_NAME, _request_timeout=REQUEST_TIMEOUT
    )
    now = now or datetime.now(UTC)
    for peer in (peering.get("status") or {}).values():
        if not isinstance(peer, dict) or peer.get("priority") != priority:
            continue
        try:
            last_seen = datetime.fromisoformat(peer["lastseen"])
            lifetime = min(float(peer["lifetime"]), PEERING_LIFETIME)
            age = (now - last_seen).total_seconds()
            if last_seen >= started_at and 0 <= age < lifetime:
                return
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    raise NotReadyError("this operator has no fresh peering heartbeat since startup")


def main() -> int:
    """Run as a readiness exec probe; never expose raw Kubernetes client errors."""
    try:
        runtime = local_runtime()
        load_api_config()
        configuration = kubernetes.client.Configuration.get_default_copy()
        configuration.retries = 0
        with kubernetes.client.ApiClient(configuration) as client:
            check_readiness(kubernetes.client.CustomObjectsApi(client), runtime)
    except NotReadyError as exc:
        print(f"not ready: {exc}")
        return 1
    except Exception as exc:
        print(f"not ready: {type(exc).__name__}")
        return 1
    print("ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
