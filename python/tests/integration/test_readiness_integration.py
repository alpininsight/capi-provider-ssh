"""Readiness is verified inside the built image against the disposable Kind API."""

import copy
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import kubernetes
import pytest

from tests.kind.runtime import eventually

pytestmark = pytest.mark.integration
NAMESPACE = "capi-provider-ssh-system"
PROBE = ["python", "-B", "-m", "capi_provider_ssh.readiness"]
LIVENESS = [
    "python",
    "-B",
    "-c",
    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=2).status)',
]


def exec_in_pod(runtime, pod, command):
    return subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            runtime.kubeconfig,
            "-n",
            NAMESPACE,
            "exec",
            pod,
            "-c",
            "controller",
            "--",
            *command,
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )


def oom_kills(runtime, pod):
    result = exec_in_pod(
        runtime,
        pod,
        ["python", "-B", "-c", "from pathlib import Path; print(Path('/sys/fs/cgroup/memory.events').read_text())"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(dict(line.split() for line in result.stdout.splitlines() if line)["oom_kill"])


def test_both_ha_replicas_are_ready_and_api_failure_does_not_fail_liveness(runtime):
    pods = runtime.core.list_namespaced_pod(
        NAMESPACE,
        label_selector="app.kubernetes.io/name=capi-provider-ssh,app.kubernetes.io/component=controller",
    ).items
    assert len(pods) == 2
    for pod in pods:
        assert pod.spec.containers[0].resources.requests["memory"] == "128Mi"
        assert pod.spec.containers[0].resources.limits["memory"] == "512Mi"
        assert oom_kills(runtime, pod.metadata.name) == 0
        # An operator may run a diagnostic concurrently with the kubelet probe.
        # Loading the generated SDK in every exec exceeded the real pod budget.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _, name=pod.metadata.name: exec_in_pod(runtime, name, PROBE), range(2)))
        for result in results:
            assert result.returncode == 0, result.stdout + result.stderr
        failed_api = exec_in_pod(
            runtime,
            pod.metadata.name,
            ["env", "KUBERNETES_SERVICE_HOST=127.0.0.1", "KUBERNETES_SERVICE_PORT=9", *PROBE],
        )
        assert failed_api.returncode != 0
        assert "not ready:" in failed_api.stdout
        alive = exec_in_pod(runtime, pod.metadata.name, LIVENESS)
        assert alive.returncode == 0 and alive.stdout.strip() == "200"
        assert oom_kills(runtime, pod.metadata.name) == 0
        current = runtime.core.read_namespaced_pod(pod.metadata.name, NAMESPACE)
        assert current.metadata.uid == pod.metadata.uid
        assert current.status.container_statuses[0].restart_count == pod.status.container_statuses[0].restart_count


def test_new_operator_with_unreachable_api_is_alive_but_never_ready(runtime):
    template = runtime.apps.read_namespaced_deployment("capi-provider-ssh-controller", NAMESPACE).spec.template
    spec = copy.deepcopy(template.spec)
    spec.affinity = None
    spec.containers[0].env.extend(
        [
            kubernetes.client.V1EnvVar(name="KUBERNETES_SERVICE_HOST", value="127.0.0.1"),
            kubernetes.client.V1EnvVar(name="KUBERNETES_SERVICE_PORT", value="9"),
        ]
    )
    name = f"readiness-no-api-{uuid.uuid4().hex[:8]}"
    body = kubernetes.client.V1Pod(
        metadata=kubernetes.client.V1ObjectMeta(name=name, labels={"capi-provider-ssh-test": "true"}), spec=spec
    )
    runtime.core.create_namespaced_pod(NAMESPACE, body)
    try:
        eventually(
            "unreachable-API operator is locally alive", lambda: exec_in_pod(runtime, name, LIVENESS).returncode == 0
        )
        result = exec_in_pod(runtime, name, PROBE)
        assert result.returncode != 0 and "not ready:" in result.stdout
        pod = runtime.core.read_namespaced_pod(name, NAMESPACE)
        assert next(condition for condition in pod.status.conditions if condition.type == "Ready").status == "False"
    finally:
        runtime.core.delete_namespaced_pod(name, NAMESPACE, grace_period_seconds=0)
