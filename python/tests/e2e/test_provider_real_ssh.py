"""Real end-to-end test: in-cluster controller + real SSH target + real bootstrap execution."""

from __future__ import annotations

import base64
import time
import uuid

import kubernetes
import pytest
from kubernetes.stream import stream

API_GROUP = "infrastructure.alpininsight.ai"
API_VERSION = "v1beta1"


def _b64(data: str) -> str:
    return base64.b64encode(data.encode("utf-8")).decode("utf-8")


def _wait_for_condition(
    custom_api: kubernetes.client.CustomObjectsApi,
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
    predicate,
    timeout: float = 180.0,
    interval: float = 2.0,
) -> dict:
    """Poll a custom object until predicate returns True."""
    deadline = time.monotonic() + timeout
    last_obj = None
    while time.monotonic() < deadline:
        obj = custom_api.get_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            name=name,
        )
        last_obj = obj
        if predicate(obj):
            return obj
        time.sleep(interval)

    raise TimeoutError(
        f"{plural}/{name} in {namespace} did not satisfy condition within {timeout}s. Last object: {last_obj}"
    )


def _exec_in_pod(core_api: kubernetes.client.CoreV1Api, namespace: str, pod: str, command: list[str]) -> str:
    """Execute command in pod and return stdout."""
    return stream(
        core_api.connect_get_namespaced_pod_exec,
        pod,
        namespace,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )


@pytest.mark.e2e
@pytest.mark.timeout(300)
def test_real_ssh_bootstrap_via_incluster_controller(core_api, custom_api, e2e_namespace, ssh_keypair, ssh_target):
    """Provision SSHMachine against a real SSH server and verify bootstrap script execution."""
    suffix = uuid.uuid4().hex[:8]
    cluster_name = f"e2e-cluster-{suffix}"
    sshcluster_name = f"e2e-sshcluster-{suffix}"
    machine_name = f"e2e-machine-{suffix}"
    sshmachine_name = f"e2e-sshmachine-{suffix}"
    bootstrap_secret_name = f"bootstrap-data-{suffix}"
    ssh_secret_name = f"ssh-key-{suffix}"

    marker_file = "/var/tmp/capi-provider-ssh-bootstrap-marker"
    marker_value = f"bootstrap-ok-{suffix}"

    bootstrap_script = f"""#!/bin/sh
set -eu
echo "{marker_value}" > {marker_file}
"""

    core_api.create_namespaced_secret(
        namespace=e2e_namespace,
        body=kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(name=bootstrap_secret_name, namespace=e2e_namespace),
            data={"value": _b64(bootstrap_script)},
        ),
    )
    core_api.create_namespaced_secret(
        namespace=e2e_namespace,
        body=kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(name=ssh_secret_name, namespace=e2e_namespace),
            data={"value": _b64(ssh_keypair.private_key)},
        ),
    )

    cluster_obj = custom_api.create_namespaced_custom_object(
        group="cluster.x-k8s.io",
        version="v1beta1",
        namespace=e2e_namespace,
        plural="clusters",
        body={
            "apiVersion": "cluster.x-k8s.io/v1beta1",
            "kind": "Cluster",
            "metadata": {
                "name": cluster_name,
                "namespace": e2e_namespace,
            },
            "spec": {
                "controlPlaneEndpoint": {
                    "host": "203.0.113.10",
                    "port": 6443,
                },
            },
        },
    )

    machine_obj = custom_api.create_namespaced_custom_object(
        group="cluster.x-k8s.io",
        version="v1beta1",
        namespace=e2e_namespace,
        plural="machines",
        body={
            "apiVersion": "cluster.x-k8s.io/v1beta1",
            "kind": "Machine",
            "metadata": {
                "name": machine_name,
                "namespace": e2e_namespace,
            },
            "spec": {
                "clusterName": cluster_name,
                "bootstrap": {
                    "dataSecretName": bootstrap_secret_name,
                },
                "infrastructureRef": {
                    "apiVersion": f"{API_GROUP}/{API_VERSION}",
                    "kind": "SSHMachine",
                    "name": sshmachine_name,
                    "namespace": e2e_namespace,
                },
            },
        },
    )

    custom_api.create_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=e2e_namespace,
        plural="sshclusters",
        body={
            "apiVersion": f"{API_GROUP}/{API_VERSION}",
            "kind": "SSHCluster",
            "metadata": {
                "name": sshcluster_name,
                "namespace": e2e_namespace,
                "ownerReferences": [
                    {
                        "apiVersion": "cluster.x-k8s.io/v1beta1",
                        "kind": "Cluster",
                        "name": cluster_name,
                        "uid": cluster_obj["metadata"]["uid"],
                    },
                ],
            },
            "spec": {
                "controlPlaneEndpoint": {
                    "host": "203.0.113.10",
                    "port": 6443,
                },
            },
        },
    )

    custom_api.create_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=e2e_namespace,
        plural="sshmachines",
        body={
            "apiVersion": f"{API_GROUP}/{API_VERSION}",
            "kind": "SSHMachine",
            "metadata": {
                "name": sshmachine_name,
                "namespace": e2e_namespace,
                "ownerReferences": [
                    {
                        "apiVersion": "cluster.x-k8s.io/v1beta1",
                        "kind": "Machine",
                        "name": machine_name,
                        "uid": machine_obj["metadata"]["uid"],
                    },
                ],
            },
            "spec": {
                "address": ssh_target.address,
                "port": ssh_target.port,
                "user": "root",
                "sshKeyRef": {
                    "name": ssh_secret_name,
                    "key": "value",
                },
            },
        },
    )

    sshcluster = _wait_for_condition(
        custom_api,
        group=API_GROUP,
        version=API_VERSION,
        plural="sshclusters",
        namespace=e2e_namespace,
        name=sshcluster_name,
        predicate=lambda obj: obj.get("status", {}).get("initialization", {}).get("provisioned") is True,
    )
    assert sshcluster["status"]["initialization"]["provisioned"] is True

    sshmachine = _wait_for_condition(
        custom_api,
        group=API_GROUP,
        version=API_VERSION,
        plural="sshmachines",
        namespace=e2e_namespace,
        name=sshmachine_name,
        predicate=lambda obj: obj.get("status", {}).get("initialization", {}).get("provisioned") is True,
    )

    assert sshmachine["spec"]["providerID"] == f"ssh://{ssh_target.address}"
    assert sshmachine["status"]["initialization"]["provisioned"] is True
    assert sshmachine["status"]["conditions"][0]["reason"] == "Provisioned"

    marker = _exec_in_pod(
        core_api,
        namespace=e2e_namespace,
        pod=ssh_target.pod_name,
        command=["cat", marker_file],
    ).strip()
    assert marker == marker_value
