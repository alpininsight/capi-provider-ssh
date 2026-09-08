"""Integration fixtures require an explicit disposable Kind API and a running provider."""

import os
import uuid
from pathlib import Path

import pytest

from tests.integration.cleanup import TeardownConfig, teardown_test_namespace
from tests.kind.runtime import Runtime


def pytest_collection_modifyitems(config, items):
    selected = os.environ.get("INTEGRATION_TESTS") == "1" or config.getoption("-m", default="") == "integration"
    if not selected:
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="select the explicit disposable integration lane"))


@pytest.fixture(scope="session")
def runtime():
    path = os.environ.get("KIND_TEST_KUBECONFIG")
    if not path:
        pytest.fail("Explicit KIND_TEST_KUBECONFIG is required; the default management context is never used")
    rt = Runtime(path, "unused")
    deployment = rt.apps.read_namespaced_deployment("capi-provider-ssh-controller", "capi-provider-ssh-system")
    assert deployment.status.ready_replicas == 2, "The integration lane requires both HA replicas"
    return rt


@pytest.fixture(scope="session")
def core_api(runtime):
    return runtime.core


@pytest.fixture(scope="session")
def custom_api(runtime):
    return runtime.api


@pytest.fixture
def test_namespace(core_api, custom_api):
    name = f"test-capi-ssh-{uuid.uuid4().hex[:8]}"
    core_api.create_namespace({"metadata": {"name": name, "labels": {"capi-provider-ssh-test": "true"}}})
    yield name
    teardown_test_namespace(
        core_api,
        custom_api,
        name,
        TeardownConfig(
            artifact_dir=Path(os.environ.get("TEARDOWN_ARTIFACT_DIR", "/tmp/capi-ssh-teardown")),
        ),
    )


@pytest.fixture
def api_runtime(runtime, test_namespace):
    return Runtime(runtime.kubeconfig, test_namespace)
