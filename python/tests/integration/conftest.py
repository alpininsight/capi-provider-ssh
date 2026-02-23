"""Integration test fixtures.

Provides ephemeral namespaces, K8s API clients, and test CRD resources.
Each test gets a unique namespace that is cleaned up on teardown.
"""

from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path

import kubernetes
import pytest

from tests.integration.cleanup import TeardownConfig, teardown_test_namespace
from tests.integration.helpers import API_GROUP, API_VERSION


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests unless explicitly requested."""
    run_integration = (
        config.getoption("-m", default="") and "integration" in config.getoption("-m", default="")
    ) or os.environ.get("INTEGRATION_TESTS") == "1"

    if run_integration:
        return

    skip_marker = pytest.mark.skip(reason="integration tests require -m integration or INTEGRATION_TESTS=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def kubeconfig():
    """Path to kubeconfig for the management cluster."""
    path = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/capi-management-tunnel.conf"))
    if not os.path.exists(path):
        pytest.skip(f"Kubeconfig not found: {path}")
    return path


@pytest.fixture(scope="session")
def k8s_client(kubeconfig):
    """Configured Kubernetes API client for the session."""
    kubernetes.config.load_kube_config(config_file=kubeconfig)
    return kubernetes.client.ApiClient()


@pytest.fixture(scope="session")
def core_api(k8s_client):
    """CoreV1Api for namespace and secret operations."""
    return kubernetes.client.CoreV1Api(k8s_client)


@pytest.fixture(scope="session")
def custom_api(k8s_client):
    """CustomObjectsApi for CRD operations."""
    return kubernetes.client.CustomObjectsApi(k8s_client)


@pytest.fixture(scope="session", autouse=True)
def _require_crds(k8s_client):
    """Skip all integration tests if SSHCluster/SSHMachine CRDs are not installed."""
    api_ext = kubernetes.client.ApiextensionsV1Api(k8s_client)
    try:
        crds = api_ext.list_custom_resource_definition()
        crd_names = [c.metadata.name for c in crds.items]
    except Exception as e:
        pytest.skip(f"Cannot list CRDs: {e}")

    required = [
        f"sshclusters.{API_GROUP}",
        f"sshmachines.{API_GROUP}",
    ]
    missing = [r for r in required if r not in crd_names]
    if missing:
        pytest.skip(f"Required CRDs not installed: {', '.join(missing)}. Apply shared/crds/ first.")


@pytest.fixture
def test_namespace(core_api, custom_api):
    """Create an ephemeral namespace for test isolation, delete on teardown."""
    ns_name = f"test-capi-ssh-{uuid.uuid4().hex[:8]}"
    ns_body = kubernetes.client.V1Namespace(
        metadata=kubernetes.client.V1ObjectMeta(
            name=ns_name,
            labels={"capi-provider-ssh-test": "true"},
        ),
    )
    core_api.create_namespace(body=ns_body)
    yield ns_name

    artifact_dir_env = os.environ.get("TEARDOWN_ARTIFACT_DIR")
    artifact_dir = Path(artifact_dir_env) if artifact_dir_env else None
    cfg = TeardownConfig(artifact_dir=artifact_dir)
    try:
        teardown_test_namespace(
            core_api=core_api,
            custom_api=custom_api,
            namespace=ns_name,
            config=cfg,
        )
    except Exception as exc:
        raise RuntimeError(f"integration teardown failed for namespace {ns_name}: {exc}") from exc


@pytest.fixture
def ssh_key_secret(core_api, test_namespace):
    """Create a test SSH key Secret in the test namespace."""
    # Use a dummy key -- SSH is mocked, but the secret must exist for _read_ssh_key
    dummy_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake-test-key\n-----END OPENSSH PRIVATE KEY-----"
    secret = kubernetes.client.V1Secret(
        metadata=kubernetes.client.V1ObjectMeta(name="test-ssh-key", namespace=test_namespace),
        data={"value": base64.b64encode(dummy_key.encode()).decode()},
    )
    core_api.create_namespaced_secret(namespace=test_namespace, body=secret)
    return "test-ssh-key"


@pytest.fixture
def bootstrap_secret(core_api, test_namespace):
    """Create a bootstrap data Secret (simulates what kubeadm bootstrap provider creates)."""
    bootstrap_data = """## template: jinja
#cloud-config
write_files:
- path: /etc/kubernetes/bootstrap-marker
  owner: root:root
  permissions: '0644'
  content: |
    marker=true
runcmd:
- echo bootstrap test
"""
    secret = kubernetes.client.V1Secret(
        metadata=kubernetes.client.V1ObjectMeta(name="test-bootstrap-data", namespace=test_namespace),
        data={"value": base64.b64encode(bootstrap_data.encode()).decode()},
    )
    core_api.create_namespaced_secret(namespace=test_namespace, body=secret)
    return "test-bootstrap-data"


@pytest.fixture
def capi_machine_cr(custom_api, test_namespace, bootstrap_secret):
    """Create a fake CAPI Machine CR that references the bootstrap data secret.

    This simulates what the CAPI core controller creates. Our SSHMachine controller
    reads the Machine to find the bootstrap data secret name.
    """
    # Check if CAPI Machine CRD exists; skip if not
    try:
        machine_body = {
            "apiVersion": "cluster.x-k8s.io/v1beta1",
            "kind": "Machine",
            "metadata": {
                "name": "test-machine-0",
                "namespace": test_namespace,
            },
            "spec": {
                "clusterName": "test-cluster",
                "bootstrap": {
                    "dataSecretName": bootstrap_secret,
                },
                "infrastructureRef": {
                    "apiVersion": f"{API_GROUP}/{API_VERSION}",
                    "kind": "SSHMachine",
                    "name": "test-sshmachine",
                    "namespace": test_namespace,
                },
            },
        }
        custom_api.create_namespaced_custom_object(
            group="cluster.x-k8s.io",
            version="v1beta1",
            namespace=test_namespace,
            plural="machines",
            body=machine_body,
        )
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            pytest.skip("CAPI Machine CRD not installed on cluster")
        raise
    return "test-machine-0"


@pytest.fixture
def cluster_owner_ref():
    """Owner reference pointing to a CAPI Cluster."""
    return [
        {
            "apiVersion": "cluster.x-k8s.io/v1beta1",
            "kind": "Cluster",
            "name": "test-cluster",
            "uid": "integration-test-uid-cluster",
        }
    ]


@pytest.fixture
def machine_owner_ref():
    """Owner reference pointing to a CAPI Machine."""
    return [
        {
            "apiVersion": "cluster.x-k8s.io/v1beta1",
            "kind": "Machine",
            "name": "test-machine-0",
            "uid": "integration-test-uid-machine",
        }
    ]
