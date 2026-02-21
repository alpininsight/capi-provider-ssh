"""Async SSH client wrapper around asyncssh.

Provides a reusable SSH client for executing commands on remote hosts
via key-based authentication. Designed for CAPI provider operations
(kubeadm init/join/reset).

Host key verification is disabled (trusted mesh assumption via
Tailscale/Headscale). A follow-up can add TOFU or known_hosts pinning
without breaking the interface.
"""

from __future__ import annotations

import dataclasses
import logging
import os

import asyncssh

logger = logging.getLogger(__name__)

# Defaults from environment (overridable per-call)
DEFAULT_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "30"))
DEFAULT_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "300"))

# Sensitive patterns to redact from logs
_REDACT_PATTERNS = ("token", "certificate-key", "discovery-token-ca-cert-hash")


def _redact(text: str) -> str:
    """Redact sensitive values from log output."""
    lines = []
    for line in text.splitlines():
        lower = line.lower()
        if any(p in lower for p in _REDACT_PATTERNS):
            lines.append("[REDACTED]")
        else:
            lines.append(line)
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class SSHResult:
    """Result of a remote command execution."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class SSHConnection:
    """Wrapper around an active asyncssh connection."""

    def __init__(self, conn: asyncssh.SSHClientConnection, address: str, port: int):
        self._conn = conn
        self._address = address
        self._port = port

    async def execute(self, command: str, timeout: int | None = None) -> SSHResult:
        """Execute a command on the remote host.

        Args:
            command: Shell command to execute.
            timeout: Command timeout in seconds (default: SSH_COMMAND_TIMEOUT).

        Returns:
            SSHResult with exit code, stdout, stderr.

        Raises:
            asyncssh.Error: On SSH protocol errors.
            TimeoutError: If command exceeds timeout.
        """
        timeout = timeout or DEFAULT_COMMAND_TIMEOUT
        logger.info("SSH execute on %s:%d (timeout=%ds)", self._address, self._port, timeout)
        logger.debug("SSH command: %s", _redact(command))

        result = await asyncssh.wait_for(self._conn.run(command, check=False), timeout=timeout)

        ssh_result = SSHResult(
            exit_code=result.exit_status or 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

        if ssh_result.success:
            logger.info("SSH command succeeded on %s:%d (exit_code=0)", self._address, self._port)
        else:
            logger.warning(
                "SSH command failed on %s:%d (exit_code=%d): %s",
                self._address,
                self._port,
                ssh_result.exit_code,
                _redact(ssh_result.stderr[:500]),
            )

        return ssh_result

    async def upload(self, content: str, path: str) -> None:
        """Write content to a file on the remote host.

        Args:
            content: File content to write.
            path: Absolute path on the remote host.
        """
        logger.info("SSH upload to %s:%d path=%s (%d bytes)", self._address, self._port, path, len(content))
        async with self._conn.start_sftp_client() as sftp, sftp.open(path, "w") as f:
            await f.write(content)

    async def close(self) -> None:
        """Close the SSH connection."""
        logger.info("SSH closing connection to %s:%d", self._address, self._port)
        self._conn.close()
        await self._conn.wait_closed()

    async def __aenter__(self) -> SSHConnection:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


class SSHClient:
    """Factory for creating SSH connections."""

    @staticmethod
    async def connect(
        address: str,
        port: int = 22,
        user: str = "root",
        key: str = "",
        timeout: int | None = None,
    ) -> SSHConnection:
        """Open an SSH connection to a remote host.

        Args:
            address: Hostname or IP address.
            port: SSH port (default: 22).
            user: SSH username (default: root).
            key: PEM-encoded private key string.
            timeout: Connection timeout in seconds (default: SSH_CONNECT_TIMEOUT).

        Returns:
            SSHConnection wrapper.

        Raises:
            asyncssh.Error: On connection or authentication failure.
            ValueError: If key cannot be parsed.
            TimeoutError: If connection exceeds timeout.
        """
        timeout = timeout or DEFAULT_CONNECT_TIMEOUT
        logger.info("SSH connecting to %s@%s:%d (timeout=%ds)", user, address, port, timeout)

        try:
            client_key = asyncssh.import_private_key(key)
        except asyncssh.KeyImportError as e:
            raise ValueError(f"Failed to parse SSH private key: {e}") from e

        conn = await asyncssh.wait_for(
            asyncssh.connect(
                host=address,
                port=port,
                username=user,
                client_keys=[client_key],
                known_hosts=None,  # Trusted mesh -- no host key verification
            ),
            timeout=timeout,
        )

        logger.info("SSH connected to %s@%s:%d", user, address, port)
        return SSHConnection(conn, address, port)
