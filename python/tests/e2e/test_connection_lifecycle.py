"""E2E tests for SSH connection lifecycle management."""

from __future__ import annotations

import asyncio

import asyncssh
import pytest

from capi_provider_ssh.ssh import SSHClient

pytestmark = pytest.mark.e2e


class TestConnectionLifecycle:
    """Validate connection open/close, reuse, and concurrent connections."""

    async def test_context_manager_closes_connection(self, strato_vm2, ssh_private_key):
        """SSHConnection works as an async context manager and closes cleanly."""
        conn = await SSHClient.connect(
            address=strato_vm2["address"],
            port=strato_vm2["port"],
            user=strato_vm2["user"],
            key=ssh_private_key,
            timeout=15,
        )

        async with conn:
            result = await conn.execute("echo inside-context")
            assert result.exit_code == 0
            assert "inside-context" in result.stdout

        # After exiting the context manager, the underlying connection should be closed.
        # asyncssh raises ChannelOpenError or ConnectionLost when using a closed connection.
        with pytest.raises((asyncssh.Error, OSError)):
            await conn.execute("echo should-fail")

    async def test_multiple_commands_single_connection(self, ssh_connection):
        """Multiple sequential commands work on a single connection."""
        results = []
        for i in range(3):
            result = await ssh_connection.execute(f"echo cmd-{i}")
            results.append(result)

        for i, result in enumerate(results):
            assert result.exit_code == 0
            assert f"cmd-{i}" in result.stdout

    async def test_concurrent_connections(self, strato_vm2, ssh_private_key):
        """Two simultaneous connections to the same host both work."""

        async def run_on_connection(tag: str) -> str:
            conn = await SSHClient.connect(
                address=strato_vm2["address"],
                port=strato_vm2["port"],
                user=strato_vm2["user"],
                key=ssh_private_key,
                timeout=15,
            )
            async with conn:
                result = await conn.execute(f"echo {tag}")
                assert result.exit_code == 0
                return result.stdout.strip()

        results = await asyncio.gather(
            run_on_connection("conn-a"),
            run_on_connection("conn-b"),
        )

        assert "conn-a" in results[0]
        assert "conn-b" in results[1]
