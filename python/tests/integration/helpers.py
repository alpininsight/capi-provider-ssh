"""Helper functions for integration tests."""

from __future__ import annotations

import time
from typing import Any

import kubernetes


API_GROUP = "infrastructure.alpininsight.ai"
API_VERSION = "v1beta1"


def create_sshcluster(
    api: kubernetes.client.CustomObjectsApi,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    owner_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create an SSHCluster custom resource."""
    body: dict[str, Any] = {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "SSHCluster",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }
    if owner_refs:
        body["metadata"]["ownerReferences"] = owner_refs
    return api.create_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshclusters",
        body=body,
    )


def create_sshmachine(
    api: kubernetes.client.CustomObjectsApi,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    owner_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create an SSHMachine custom resource."""
    body: dict[str, Any] = {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "SSHMachine",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }
    if owner_refs:
        body["metadata"]["ownerReferences"] = owner_refs
    return api.create_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshmachines",
        body=body,
    )


def get_sshcluster(
    api: kubernetes.client.CustomObjectsApi,
    name: str,
    namespace: str,
) -> dict[str, Any]:
    """Get an SSHCluster custom resource."""
    return api.get_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshclusters",
        name=name,
    )


def get_sshmachine(
    api: kubernetes.client.CustomObjectsApi,
    name: str,
    namespace: str,
) -> dict[str, Any]:
    """Get an SSHMachine custom resource."""
    return api.get_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshmachines",
        name=name,
    )


def wait_for_status(
    api: kubernetes.client.CustomObjectsApi,
    name: str,
    namespace: str,
    plural: str,
    condition: callable,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> dict[str, Any]:
    """Poll a custom resource until condition is met or timeout expires.

    Args:
        api: CustomObjectsApi instance
        name: Resource name
        namespace: Resource namespace
        plural: CRD plural (e.g. "sshclusters")
        condition: Callable that takes the resource dict and returns True when satisfied
        timeout: Maximum wait time in seconds
        interval: Poll interval in seconds

    Returns:
        The resource dict when condition is met

    Raises:
        TimeoutError: If condition is not met within timeout
    """
    deadline = time.monotonic() + timeout
    last_resource = None
    while time.monotonic() < deadline:
        resource = api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
        last_resource = resource
        if condition(resource):
            return resource
        time.sleep(interval)
    status = last_resource.get("status", {}) if last_resource else {}
    raise TimeoutError(f"{plural}/{name} in {namespace} did not meet condition within {timeout}s. Last status: {status}")
