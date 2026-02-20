"""Fixtures for real SSH end-to-end tests."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass

import kubernetes
import pytest

API_GROUP = "infrastructure.alpininsight.ai"
API_VERSION = "v1beta1"
DEFAULT_KUBECONFIG = os.path.expanduser("~/.kube/config")
SSH_TARGET_PORT = 2222
DEFAULT_SSH_TARGET_IMAGE = "capi-provider-ssh-ssh-target:e2e"


@dataclass
class SSHKeyPair:
    """Ephemeral SSH keypair used by e2e tests."""

    private_key: str
    public_key: str


@dataclass
class SSHTarget:
    """In-cluster SSH target endpoint metadata."""

    address: str
    port: int
    pod_name: str


def pytest_collection_modifyitems(config, items):
    """Auto-skip e2e tests unless explicitly requested."""
    run_e2e = (config.getoption("-m", default="") and "e2e" in config.getoption("-m", default="")) or os.environ.get(
        "E2E_TESTS"
    ) == "1"

    if run_e2e:
        return

    skip_marker = pytest.mark.skip(reason="e2e tests require -m e2e or E2E_TESTS=1")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_marker)


def _wait_for_pod_ready(
    core_api: kubernetes.client.CoreV1Api, namespace: str, name: str, timeout: float = 120.0
) -> None:
    """Wait until pod is Running and Ready."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pod = core_api.read_namespaced_pod(name=name, namespace=namespace)
        if pod.status.phase == "Running":
            conditions = pod.status.conditions or []
            if any(c.type == "Ready" and c.status == "True" for c in conditions):
                return
        time.sleep(1)
    raise TimeoutError(f"Pod {namespace}/{name} did not become Ready within {timeout}s")


def _wait_for_deployment_ready(
    apps_api: kubernetes.client.AppsV1Api,
    namespace: str,
    name: str,
    timeout: float = 180.0,
) -> None:
    """Wait until deployment has at least one available replica."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        deployment = apps_api.read_namespaced_deployment(name=name, namespace=namespace)
        if (deployment.status.available_replicas or 0) >= 1:
            return
        time.sleep(2)
    raise TimeoutError(f"Deployment {namespace}/{name} did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def kubeconfig():
    """Path to kubeconfig for e2e tests."""
    path = os.environ.get("KUBECONFIG", DEFAULT_KUBECONFIG)
    if not os.path.exists(path):
        pytest.skip(f"Kubeconfig not found: {path}")
    return path


@pytest.fixture(scope="session")
def k8s_client(kubeconfig):
    """Configured Kubernetes API client."""
    kubernetes.config.load_kube_config(config_file=kubeconfig)
    return kubernetes.client.ApiClient()


@pytest.fixture(scope="session")
def core_api(k8s_client):
    """CoreV1Api client."""
    return kubernetes.client.CoreV1Api(k8s_client)


@pytest.fixture(scope="session")
def apps_api(k8s_client):
    """AppsV1Api client."""
    return kubernetes.client.AppsV1Api(k8s_client)


@pytest.fixture(scope="session")
def custom_api(k8s_client):
    """CustomObjectsApi client."""
    return kubernetes.client.CustomObjectsApi(k8s_client)


@pytest.fixture(scope="session", autouse=True)
def _require_e2e_crds(k8s_client):
    """Skip e2e tests if required CRDs are not installed."""
    api_ext = kubernetes.client.ApiextensionsV1Api(k8s_client)
    try:
        crds = api_ext.list_custom_resource_definition()
        crd_names = [c.metadata.name for c in crds.items]
    except Exception as exc:  # pragma: no cover - environment issue
        pytest.skip(f"Cannot list CRDs: {exc}")

    required = [
        f"sshclusters.{API_GROUP}",
        f"sshmachines.{API_GROUP}",
        "clusters.cluster.x-k8s.io",
        "machines.cluster.x-k8s.io",
    ]
    missing = [name for name in required if name not in crd_names]
    if missing:
        pytest.skip(
            "Required CRDs not installed: "
            + ", ".join(missing)
            + ". Apply shared/crds and python/tests/e2e/manifests/capi-core-crds.yaml first."
        )


@pytest.fixture(scope="session", autouse=True)
def _require_controller_deployment(apps_api):
    """Skip if controller deployment is not present/ready."""
    namespace = "capi-provider-ssh-system"
    name = "capi-provider-ssh-controller"
    try:
        _wait_for_deployment_ready(apps_api, namespace=namespace, name=name)
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            pytest.skip(
                "Controller deployment missing. Apply python/deploy and set image before running e2e tests.",
            )
        raise


@pytest.fixture
def e2e_namespace(core_api):
    """Create an isolated namespace for e2e resources."""
    ns_name = f"e2e-capi-ssh-{uuid.uuid4().hex[:8]}"
    ns = kubernetes.client.V1Namespace(
        metadata=kubernetes.client.V1ObjectMeta(
            name=ns_name,
            labels={
                "capi-provider-ssh-test": "true",
                "capi-provider-ssh-suite": "real-ssh",
            },
        ),
    )
    core_api.create_namespace(body=ns)
    yield ns_name
    core_api.delete_namespace(name=ns_name, body=kubernetes.client.V1DeleteOptions(propagation_policy="Background"))


@pytest.fixture(scope="session")
def ssh_keypair() -> SSHKeyPair:
    """Generate an ephemeral ED25519 keypair for the SSH target."""
    with tempfile.TemporaryDirectory(prefix="capi-provider-ssh-e2e-keys-") as tmpdir:
        key_path = os.path.join(tmpdir, "id_ed25519")
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key_path, "-C", "capi-provider-ssh-e2e"],
            check=True,
            capture_output=True,
            text=True,
        )
        with open(key_path, encoding="utf-8") as f:
            private_key = f.read()
        with open(f"{key_path}.pub", encoding="utf-8") as f:
            public_key = f.read().strip()
    return SSHKeyPair(private_key=private_key, public_key=public_key)


@pytest.fixture(scope="session")
def ssh_target_image() -> str:
    """SSH target image to use in e2e tests."""
    return os.environ.get("E2E_SSH_TARGET_IMAGE", DEFAULT_SSH_TARGET_IMAGE)


@pytest.fixture
def ssh_target(core_api, e2e_namespace, ssh_keypair, ssh_target_image) -> SSHTarget:
    """Create an in-cluster SSH server pod and Service using public-key auth."""
    labels = {"app": "ssh-target", "suite": "capi-provider-ssh-e2e"}
    pod_name = "ssh-target"
    svc_name = "ssh-target"

    pod = kubernetes.client.V1Pod(
        metadata=kubernetes.client.V1ObjectMeta(
            name=pod_name,
            namespace=e2e_namespace,
            labels=labels,
        ),
        spec=kubernetes.client.V1PodSpec(
            containers=[
                kubernetes.client.V1Container(
                    name="sshd",
                    image=ssh_target_image,
                    image_pull_policy="IfNotPresent",
                    env=[
                        kubernetes.client.V1EnvVar(name="AUTHORIZED_KEY", value=ssh_keypair.public_key),
                    ],
                    ports=[
                        kubernetes.client.V1ContainerPort(container_port=SSH_TARGET_PORT),
                    ],
                    readiness_probe=kubernetes.client.V1Probe(
                        tcp_socket=kubernetes.client.V1TCPSocketAction(port=SSH_TARGET_PORT),
                        initial_delay_seconds=2,
                        period_seconds=2,
                    ),
                ),
            ],
        ),
    )
    core_api.create_namespaced_pod(namespace=e2e_namespace, body=pod)

    service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=svc_name, namespace=e2e_namespace),
        spec=kubernetes.client.V1ServiceSpec(
            selector=labels,
            ports=[
                kubernetes.client.V1ServicePort(
                    port=SSH_TARGET_PORT,
                    target_port=SSH_TARGET_PORT,
                    protocol="TCP",
                ),
            ],
        ),
    )
    core_api.create_namespaced_service(namespace=e2e_namespace, body=service)

    _wait_for_pod_ready(core_api, namespace=e2e_namespace, name=pod_name)

    return SSHTarget(
        address=f"{svc_name}.{e2e_namespace}.svc.cluster.local",
        port=SSH_TARGET_PORT,
        pod_name=pod_name,
    )
