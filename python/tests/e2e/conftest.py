"""E2E test fixtures for real SSH targets.

Provides session-scoped SSH connection details and function-scoped cleanup
to ensure no test artifacts leak between tests.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from capi_provider_ssh.ssh import SSHClient


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


@pytest.fixture(scope="session")
def strato_vm2():
    """SSH target details for strato-vm2.

    Returns dict with address, port, user. Skips if host is unreachable.
    Override with E2E_SSH_HOST, E2E_SSH_PORT, E2E_SSH_USER env vars.
    """
    host = os.environ.get("E2E_SSH_HOST", "217.154.172.8")
    port = int(os.environ.get("E2E_SSH_PORT", "22"))
    user = os.environ.get("E2E_SSH_USER", "root")

    # Pre-flight reachability check (TCP ping via nc, 5s timeout)
    try:
        subprocess.run(
            ["nc", "-z", "-w", "5", host, str(port)],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip(f"SSH target {host}:{port} is unreachable")

    return {"address": host, "port": port, "user": user}


@pytest.fixture(scope="session")
def ssh_private_key():
    """Read the SSH private key from disk.

    Uses E2E_SSH_KEY_PATH env var (default: ~/.ssh/id_ed25519).
    Skips if the key file doesn't exist.
    """
    raw_key_path = os.environ.get("E2E_SSH_KEY_PATH", "~/.ssh/id_ed25519")
    key_path = os.path.expanduser(os.path.expandvars(raw_key_path))
    if not os.path.exists(key_path):
        pytest.skip(f"SSH private key not found: {key_path}")
    with open(key_path) as f:
        return f.read()


@pytest.fixture
async def ssh_connection(strato_vm2, ssh_private_key):
    """Open a real SSH connection to the target host. Closes on teardown."""
    conn = await SSHClient.connect(
        address=strato_vm2["address"],
        port=strato_vm2["port"],
        user=strato_vm2["user"],
        key=ssh_private_key,
        timeout=15,
    )
    yield conn
    await conn.close()


@pytest.fixture(autouse=True)
async def cleanup_marker_files(strato_vm2, ssh_private_key):
    """Remove /tmp/capi-e2e-* marker files after each test."""
    yield
    try:
        conn = await SSHClient.connect(
            address=strato_vm2["address"],
            port=strato_vm2["port"],
            user=strato_vm2["user"],
            key=ssh_private_key,
            timeout=10,
        )
        async with conn:
            await conn.execute("rm -f /tmp/capi-e2e-*", timeout=10)
    except Exception:
        pass  # Best-effort cleanup; don't fail tests over cleanup issues
