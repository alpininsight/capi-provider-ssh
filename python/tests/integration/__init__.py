"""Integration tests for capi-provider-ssh.

These tests run against a real Kubernetes management cluster and validate
the full CRD lifecycle (create, reconcile, status patch, delete).
SSH connections are mocked -- only K8s API interactions are real.

Requirements:
- KUBECONFIG pointing to a cluster with SSHCluster/SSHMachine CRDs applied
- Run with: uv run pytest -m integration -v
"""
