"""Readiness is verified inside the built image against the disposable Kind API."""

import copy
import subprocess
import uuid

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


def test_both_ha_replicas_are_ready_and_api_failure_does_not_fail_liveness(runtime):
    pods = runtime.core.list_namespaced_pod(
        NAMESPACE,
        label_selector="app.kubernetes.io/name=capi-provider-ssh,app.kubernetes.io/component=controller",
    ).items
    assert len(pods) == 2
    for pod in pods:
        result = exec_in_pod(runtime, pod.metadata.name, PROBE)
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
