"""Shared test fixtures for capi-provider-ssh."""

import pytest


@pytest.fixture
def sshcluster_spec():
    """Minimal SSHCluster spec."""
    return {
        "controlPlaneEndpoint": {
            "host": "10.0.0.1",
            "port": 6443,
        },
    }


@pytest.fixture
def sshcluster_meta_with_owner():
    """SSHCluster metadata with CAPI Cluster ownerReference."""
    return {
        "ownerReferences": [
            {
                "apiVersion": "cluster.x-k8s.io/v1beta1",
                "kind": "Cluster",
                "name": "test-cluster",
                "uid": "abc-123",
            }
        ]
    }


@pytest.fixture
def sshcluster_meta_no_owner():
    """SSHCluster metadata without ownerReference."""
    return {}


@pytest.fixture
def sshmachine_spec():
    """Minimal SSHMachine spec."""
    return {
        "address": "100.64.0.10",
        "port": 22,
        "user": "root",
        "sshKeyRef": {
            "name": "ssh-key-secret",
            "key": "value",
        },
    }


@pytest.fixture
def sshmachine_meta_with_owner():
    """SSHMachine metadata with CAPI Machine ownerReference."""
    return {
        "ownerReferences": [
            {
                "apiVersion": "cluster.x-k8s.io/v1beta1",
                "kind": "Machine",
                "name": "test-machine-0",
                "uid": "def-456",
            }
        ]
    }
