"""E2E tests for SSH connectivity against a real SSH target."""

from __future__ import annotations

import pytest

from capi_provider_ssh.ssh import SSHClient

pytestmark = pytest.mark.e2e


class TestSSHConnectivity:
    """Validate SSHClient.connect() and SSHConnection methods against a real host."""

    async def test_connect_and_execute_echo(self, ssh_connection):
        """SSHClient.connect() + execute returns exit_code=0 for a simple echo."""
        result = await ssh_connection.execute("echo hello")
        assert result.exit_code == 0
        assert result.success is True
        assert "hello" in result.stdout

    async def test_execute_returns_stdout(self, ssh_connection):
        """stdout is captured correctly from a command."""
        result = await ssh_connection.execute("cat /etc/hostname")
        assert result.exit_code == 0
        assert len(result.stdout.strip()) > 0

    async def test_execute_returns_stderr(self, ssh_connection):
        """stderr is captured correctly from a command writing to stderr."""
        result = await ssh_connection.execute("echo errormsg >&2")
        assert "errormsg" in result.stderr

    async def test_execute_nonzero_exit(self, ssh_connection):
        """A failing command returns the correct non-zero exit code."""
        result = await ssh_connection.execute("false")
        assert result.exit_code == 1
        assert result.success is False

    async def test_connect_timeout_unreachable(self, ssh_private_key):
        """Connecting to an unreachable address with a short timeout raises TimeoutError."""
        with pytest.raises(TimeoutError):
            await SSHClient.connect(
                address="192.0.2.1",  # TEST-NET-1 (RFC 5737), guaranteed unreachable
                port=22,
                user="root",
                key=ssh_private_key,
                timeout=3,
            )

    async def test_upload_and_read_file(self, ssh_connection):
        """Upload content via SFTP and read it back with cat."""
        marker_content = "capi-e2e-upload-marker-12345"
        remote_path = "/tmp/capi-e2e-upload-test"

        await ssh_connection.upload(marker_content, remote_path)
        result = await ssh_connection.execute(f"cat {remote_path}")

        assert result.exit_code == 0
        assert marker_content in result.stdout
