"""Deterministic teardown helpers for integration test namespaces."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kubernetes

TEST_NAMESPACE_PREFIX = "test-capi-ssh-"
TEST_NAMESPACE_LABEL_KEY = "capi-provider-ssh-test"
TEST_NAMESPACE_LABEL_VALUE = "true"

SSH_API_GROUP = "infrastructure.alpininsight.ai"
SSH_API_VERSION = "v1beta1"

CAPI_API_GROUP = "cluster.x-k8s.io"
CAPI_API_VERSION = "v1beta1"

BOOTSTRAP_API_GROUP = "bootstrap.cluster.x-k8s.io"
BOOTSTRAP_API_VERSION = "v1beta1"


@dataclass(frozen=True)
class TeardownConfig:
    """Runtime configuration for integration teardown."""

    soft_timeout_seconds: float = 60.0
    hard_timeout_seconds: float = 180.0
    poll_interval_seconds: float = 2.0
    artifact_dir: Path | None = None


@dataclass
class TeardownReport:
    """Summary of teardown execution."""

    namespace: str
    deleted_resources: dict[str, int]
    remediated_finalizers: int
    duration_seconds: float
    debug_bundle_path: str | None = None


def is_test_namespace(name: str, labels: dict[str, str] | None) -> bool:
    """Return True when namespace is eligible for test teardown operations."""
    if not name.startswith(TEST_NAMESPACE_PREFIX):
        return False
    if not labels:
        return False
    return labels.get(TEST_NAMESPACE_LABEL_KEY) == TEST_NAMESPACE_LABEL_VALUE


def teardown_test_namespace(
    core_api: kubernetes.client.CoreV1Api,
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    config: TeardownConfig | None = None,
) -> TeardownReport:
    """Delete test resources in a deterministic order and assert no residue."""
    cfg = config or TeardownConfig()
    started = time.monotonic()
    deleted_resources: dict[str, int] = {}
    remediated_finalizers = 0
    debug_bundle_path: str | None = None

    try:
        namespace_obj = _read_namespace(core_api, namespace)
        if namespace_obj is None:
            return TeardownReport(
                namespace=namespace,
                deleted_resources={},
                remediated_finalizers=0,
                duration_seconds=round(time.monotonic() - started, 3),
            )

        labels = dict(namespace_obj.metadata.labels or {})
        if not is_test_namespace(namespace, labels):
            raise ValueError(
                f"Refusing teardown for non-test namespace {namespace!r}. "
                f"Required: prefix {TEST_NAMESPACE_PREFIX!r} and label "
                f"{TEST_NAMESPACE_LABEL_KEY}={TEST_NAMESPACE_LABEL_VALUE!r}."
            )

        resources = [
            # Prefer CAPI core resources first so CAPI drives infrastructure deletion.
            ("machines", CAPI_API_GROUP, CAPI_API_VERSION),
            # Sweep infrastructure resources afterward to remove any leftovers.
            ("sshmachines", SSH_API_GROUP, SSH_API_VERSION),
            ("sshclusters", SSH_API_GROUP, SSH_API_VERSION),
            ("kubeadmconfigs", BOOTSTRAP_API_GROUP, BOOTSTRAP_API_VERSION),
        ]

        for plural, group, version in resources:
            deleted_resources[plural] = _delete_custom_objects(custom_api, namespace, group, version, plural)

        deleted_resources["secrets"] = _delete_test_secrets(core_api, namespace)

        for plural, group, version in resources:
            if not _wait_for_absence(
                custom_api,
                namespace=namespace,
                group=group,
                version=version,
                plural=plural,
                timeout_seconds=cfg.soft_timeout_seconds,
                poll_interval_seconds=cfg.poll_interval_seconds,
            ):
                remediated_finalizers += _clear_stuck_finalizers(
                    custom_api,
                    namespace=namespace,
                    group=group,
                    version=version,
                    plural=plural,
                )
                _wait_for_absence(
                    custom_api,
                    namespace=namespace,
                    group=group,
                    version=version,
                    plural=plural,
                    timeout_seconds=cfg.soft_timeout_seconds,
                    poll_interval_seconds=cfg.poll_interval_seconds,
                )

        _delete_namespace(core_api, namespace)
        _wait_for_namespace_absence(
            core_api,
            namespace=namespace,
            timeout_seconds=cfg.hard_timeout_seconds,
            poll_interval_seconds=cfg.poll_interval_seconds,
        )

        residue = collect_namespace_residue(core_api, custom_api, namespace)
        if any(residue.values()):
            raise AssertionError(f"Teardown residue detected for namespace {namespace}: {residue}")

    except Exception:
        if cfg.artifact_dir:
            bundle = collect_teardown_debug_bundle(
                core_api=core_api,
                custom_api=custom_api,
                namespace=namespace,
                artifact_dir=cfg.artifact_dir,
            )
            debug_bundle_path = str(bundle)
        raise

    duration = round(time.monotonic() - started, 3)
    return TeardownReport(
        namespace=namespace,
        deleted_resources=deleted_resources,
        remediated_finalizers=remediated_finalizers,
        duration_seconds=duration,
        debug_bundle_path=debug_bundle_path,
    )


def collect_namespace_residue(
    core_api: kubernetes.client.CoreV1Api,
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
) -> dict[str, list[str]]:
    """Collect potentially leaked resources for a test namespace."""
    residue: dict[str, list[str]] = {
        "namespace": [],
        "sshmachines": [],
        "sshclusters": [],
        "machines": [],
        "kubeadmconfigs": [],
        "secrets": [],
    }

    namespace_obj = _read_namespace(core_api, namespace)
    if namespace_obj is not None:
        residue["namespace"].append(namespace)

    resources = [
        ("machines", CAPI_API_GROUP, CAPI_API_VERSION),
        ("sshmachines", SSH_API_GROUP, SSH_API_VERSION),
        ("sshclusters", SSH_API_GROUP, SSH_API_VERSION),
        ("kubeadmconfigs", BOOTSTRAP_API_GROUP, BOOTSTRAP_API_VERSION),
    ]
    for plural, group, version in resources:
        items = _list_custom_objects(custom_api, namespace, group, version, plural)
        residue[plural].extend(item["metadata"]["name"] for item in items)

    for secret in _list_secrets(core_api, namespace):
        if _is_test_secret(secret.metadata.name):
            residue["secrets"].append(secret.metadata.name)

    return residue


def collect_teardown_debug_bundle(
    core_api: kubernetes.client.CoreV1Api,
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    artifact_dir: Path,
) -> Path:
    """Write teardown diagnostics for failed cleanup to disk."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = artifact_dir / f"{namespace}-{int(time.time())}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    residue = collect_namespace_residue(core_api, custom_api, namespace)
    (bundle_dir / "residue.json").write_text(json.dumps(residue, indent=2, sort_keys=True), encoding="utf-8")

    namespace_obj = _read_namespace(core_api, namespace)
    namespace_payload: dict[str, Any] = {}
    if namespace_obj is not None:
        namespace_payload = {
            "name": namespace_obj.metadata.name,
            "labels": dict(namespace_obj.metadata.labels or {}),
            "finalizers": list(namespace_obj.metadata.finalizers or []),
            "deletionTimestamp": str(namespace_obj.metadata.deletion_timestamp or ""),
            "phase": str(namespace_obj.status.phase or ""),
        }
    (bundle_dir / "namespace.json").write_text(
        json.dumps(namespace_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    resources = [
        ("machines", CAPI_API_GROUP, CAPI_API_VERSION),
        ("sshmachines", SSH_API_GROUP, SSH_API_VERSION),
        ("sshclusters", SSH_API_GROUP, SSH_API_VERSION),
        ("kubeadmconfigs", BOOTSTRAP_API_GROUP, BOOTSTRAP_API_VERSION),
    ]
    for plural, group, version in resources:
        items = _list_custom_objects(custom_api, namespace, group, version, plural)
        (bundle_dir / f"{plural}.json").write_text(
            json.dumps(items, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    events_payload: list[dict[str, Any]] = []
    try:
        events = core_api.list_namespaced_event(namespace=namespace).items
    except kubernetes.client.ApiException as exc:
        if exc.status != 404:
            raise
    else:
        for event in events:
            events_payload.append(
                {
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "count": event.count,
                    "lastTimestamp": str(event.last_timestamp or ""),
                    "involvedObject": {
                        "kind": event.involved_object.kind,
                        "name": event.involved_object.name,
                    },
                }
            )
    (bundle_dir / "events.json").write_text(
        json.dumps(events_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return bundle_dir


def _read_namespace(core_api: kubernetes.client.CoreV1Api, namespace: str):
    try:
        return core_api.read_namespace(namespace)
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _delete_namespace(core_api: kubernetes.client.CoreV1Api, namespace: str) -> None:
    try:
        core_api.delete_namespace(
            name=namespace,
            body=kubernetes.client.V1DeleteOptions(propagation_policy="Background"),
        )
    except kubernetes.client.ApiException as exc:
        if exc.status != 404:
            raise


def _wait_for_namespace_absence(
    core_api: kubernetes.client.CoreV1Api,
    namespace: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _read_namespace(core_api, namespace) is None:
            return True
        time.sleep(poll_interval_seconds)
    return False


def _list_custom_objects(
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
) -> list[dict[str, Any]]:
    try:
        response = custom_api.list_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
        )
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            return []
        raise
    return list(response.get("items", []))


def _delete_custom_objects(
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
) -> int:
    deleted = 0
    for item in _list_custom_objects(custom_api, namespace, group, version, plural):
        name = item["metadata"]["name"]
        try:
            custom_api.delete_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
                body=kubernetes.client.V1DeleteOptions(propagation_policy="Background"),
            )
        except kubernetes.client.ApiException as exc:
            if exc.status != 404:
                raise
        else:
            deleted += 1
    return deleted


def _wait_for_absence(
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _list_custom_objects(custom_api, namespace, group, version, plural):
            return True
        time.sleep(poll_interval_seconds)
    return False


def _clear_stuck_finalizers(
    custom_api: kubernetes.client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
) -> int:
    patched = 0
    for item in _list_custom_objects(custom_api, namespace, group, version, plural):
        metadata = item.get("metadata", {})
        name = metadata.get("name")
        if not name:
            continue
        finalizers = list(metadata.get("finalizers") or [])
        deletion_ts = metadata.get("deletionTimestamp")
        if not finalizers or not deletion_ts:
            continue
        custom_api.patch_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            name=name,
            body={
                "metadata": {
                    "finalizers": [],
                    "annotations": {
                        "capi-provider-ssh.test/finalizer-remediated-at": str(int(time.time())),
                    },
                }
            },
        )
        patched += 1
    return patched


def _list_secrets(core_api: kubernetes.client.CoreV1Api, namespace: str):
    try:
        return core_api.list_namespaced_secret(namespace=namespace).items
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            return []
        raise


def _is_test_secret(name: str | None) -> bool:
    if not name:
        return False
    return name.startswith("test-")


def _delete_test_secrets(core_api: kubernetes.client.CoreV1Api, namespace: str) -> int:
    deleted = 0
    for secret in _list_secrets(core_api, namespace):
        name = secret.metadata.name
        if not _is_test_secret(name):
            continue
        try:
            core_api.delete_namespaced_secret(name=name, namespace=namespace)
        except kubernetes.client.ApiException as exc:
            if exc.status != 404:
                raise
        else:
            deleted += 1
    return deleted
