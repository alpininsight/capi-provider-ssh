"""Real CAPI init, control-plane/worker joins, cleanup, reuse and abrupt failover."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from capi_provider_ssh.operations import owned_command
from tests.kind.runtime import CAPI_GROUP, SSH_GROUP, Runtime, eventually, run

pytestmark = [pytest.mark.kind, pytest.mark.timeout(1800)]


def test_capi_lifecycle_and_inflight_provider_failover():
    rt = Runtime(os.environ["KIND_TEST_KUBECONFIG"], f"test-capi-ssh-life-{uuid.uuid4().hex[:8]}")
    directory = Path(os.environ["KIND_TEST_ARTIFACTS"]) / rt.namespace
    rt.core.create_namespace({"metadata": {"name": rt.namespace, "labels": {"capi-provider-ssh-test": "true"}}})
    try:
        for role in ("cp-0", "cp-1", "cp-2", "worker-0"):
            rt.prepare_target(role)
        rt.start_control_plane()
        rt.wait_provisioned(1)
        rt.install_cni()
        rt.ready_nodes(1)
        rt.patch("controlplane.cluster.x-k8s.io", "kubeadmcontrolplanes", "workload", {"spec": {"replicas": 3}})
        rt.start_workers()
        rt.wait_provisioned(4)
        rt.ready_nodes(4)
        before = rt.get(SSH_GROUP, "sshhosts", "worker-0")["spec"]["consumerRef"]["uid"]
        rt.patch(CAPI_GROUP, "machinedeployments", "workers", {"spec": {"replicas": 0}})
        eventually(
            "CAPI cleanup releases worker claim",
            lambda: not rt.get(SSH_GROUP, "sshhosts", "worker-0")["spec"].get("consumerRef"),
        )
        run(
            "docker",
            "exec",
            rt.container("worker-0"),
            "sh",
            "-ceu",
            "test ! -e /etc/kubernetes/kubelet.conf; test ! -e /var/lib/capi-provider-ssh/owner",
        )
        # A lost owner marker with residual control-plane data is not proof of cleanup.
        for residual in ("/var/lib/etcd/member", "/etc/kubernetes/manifests/kube-apiserver.yaml"):
            run("docker", "exec", rt.container("worker-0"), "mkdir", "-p", residual)
            rejected = subprocess.run(
                [
                    "docker",
                    "exec",
                    rt.container("worker-0"),
                    "sh",
                    "-c",
                    owned_command(before, "touch /tmp/capi-forbidden", cleaned_retry=True),
                ],
                capture_output=True,
            )
            assert rejected.returncode == 78
            run("docker", "exec", rt.container("worker-0"), "test", "!", "-e", "/tmp/capi-forbidden")
            run("docker", "exec", rt.container("worker-0"), "rm", "-rf", residual)
        result = rt.reuse_worker_with_failover()
        after = rt.get(SSH_GROUP, "sshhosts", "worker-0")["spec"]["consumerRef"]["uid"]
        assert before != after
        # The actual remote guard must reject a different UID before any mutation.
        rejected = subprocess.run(
            [
                "docker",
                "exec",
                rt.container("worker-0"),
                "sh",
                "-c",
                owned_command("different-uid", "touch /tmp/capi-forbidden"),
            ],
            capture_output=True,
        )
        assert rejected.returncode == 78
        run("docker", "exec", rt.container("worker-0"), "test", "!", "-e", "/tmp/capi-forbidden")
        result.update(oldMachineUID=before, newMachineUID=after, readyNodes=4, capi="1.12.11", kubernetes="1.34.11")
        rt.snapshot(directory)
        (directory / "lifecycle-evidence.json").write_text(json.dumps(result, indent=2))
    finally:
        rt.snapshot(directory)
        # Delete through CAPI and wait. Never strip finalizers or delete SSH Secrets first.
        clusters = rt.api.list_namespaced_custom_object(CAPI_GROUP, "v1beta1", rt.namespace, "clusters")["items"]
        if clusters:
            rt.api.delete_namespaced_custom_object(CAPI_GROUP, "v1beta1", rt.namespace, "clusters", "workload")
            eventually(
                "CAPI finalizers and remote cleanup",
                lambda: (
                    not rt.machines()
                    and not rt.api.list_namespaced_custom_object(CAPI_GROUP, "v1beta1", rt.namespace, "clusters")[
                        "items"
                    ]
                ),
                timeout=600,
            )
        for target in rt.targets.values():
            run("docker", "rm", "-fv", target["container"])
        rt.core.delete_namespace(rt.namespace)
        eventually(
            "test namespace deletion",
            lambda: rt.namespace not in {item.metadata.name for item in rt.core.list_namespace().items},
        )
