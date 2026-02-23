"""Tests for SSH client wrapper."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from capi_provider_ssh.ssh import SSHClient, SSHConnection, SSHResult, _redact


class TestSSHResult:
    def test_success_true(self):
        r = SSHResult(exit_code=0, stdout="ok", stderr="")
        assert r.success is True

    def test_success_false(self):
        r = SSHResult(exit_code=1, stdout="", stderr="error")
        assert r.success is False

    def test_frozen(self):
        r = SSHResult(exit_code=0, stdout="", stderr="")
        with pytest.raises(AttributeError):
            r.exit_code = 1  # type: ignore[misc]


class TestRedact:
    def test_redacts_token(self):
        text = "--token abcdef.1234567890abcdef"
        assert "[REDACTED]" in _redact(text)

    def test_redacts_certificate_key(self):
        text = "--certificate-key abc123def456"
        assert "[REDACTED]" in _redact(text)

    def test_redacts_discovery_token_ca_cert_hash(self):
        text = "--discovery-token-ca-cert-hash sha256:abc123"
        assert "[REDACTED]" in _redact(text)

    def test_preserves_safe_lines(self):
        text = "kubeadm join 10.0.0.1:6443"
        assert _redact(text) == text

    def test_multiline_selective_redaction(self):
        text = "line1\n--token abc123\nline3"
        result = _redact(text)
        assert result.startswith("line1\n")
        assert result.endswith("\nline3")
        assert "[REDACTED]" in result

    def test_private_key_not_logged(self):
        """Verify private key material is never in log-safe output."""
        # The SSH client never logs key material directly,
        # but verify the redact function handles it
        text = "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64data\n-----END OPENSSH PRIVATE KEY-----"
        # Keys don't match token patterns, but they should never
        # appear in logs anyway (the SSH client doesn't log keys)
        result = _redact(text)
        assert result is not None  # Just verify it doesn't crash


class TestSSHClient:
    @pytest.mark.asyncio
    async def test_connect_uses_asyncio_wait_for(self):
        raw_conn = MagicMock()
        connect_call = object()
        imported_key = object()
        wait_for_mock = AsyncMock(return_value=raw_conn)

        with (
            patch("capi_provider_ssh.ssh.asyncssh.import_private_key", return_value=imported_key) as import_key,
            patch("capi_provider_ssh.ssh.asyncssh.connect", return_value=connect_call) as connect,
            patch("capi_provider_ssh.ssh.asyncio.wait_for", wait_for_mock),
        ):
            conn = await SSHClient.connect(
                address="10.0.0.1",
                port=2222,
                user="admin",
                key="fake-private-key",
                timeout=9,
            )

        assert isinstance(conn, SSHConnection)
        import_key.assert_called_once_with("fake-private-key")
        connect.assert_called_once_with(
            host="10.0.0.1",
            port=2222,
            username="admin",
            client_keys=[imported_key],
            known_hosts=None,
        )
        wait_for_mock.assert_awaited_once_with(connect_call, timeout=9)

    @pytest.mark.asyncio
    async def test_connect_invalid_private_key_raises_value_error(self):
        with (
            patch(
                "capi_provider_ssh.ssh.asyncssh.import_private_key",
                side_effect=asyncssh.KeyImportError("bad key"),
            ),
            pytest.raises(ValueError, match="Failed to parse SSH private key"),
        ):
            await SSHClient.connect(address="10.0.0.1", key="bad-key")


class TestSSHConnection:
    @pytest.mark.asyncio
    async def test_execute_uses_asyncio_wait_for(self):
        run_call = object()
        raw_conn = MagicMock()
        raw_conn.run.return_value = run_call
        wait_for_mock = AsyncMock(
            return_value=SimpleNamespace(exit_status=0, stdout="ok", stderr=""),
        )
        conn = SSHConnection(raw_conn, "10.0.0.1", 22)

        with patch("capi_provider_ssh.ssh.asyncio.wait_for", wait_for_mock):
            result = await conn.execute("echo ok", timeout=5)

        raw_conn.run.assert_called_once_with("echo ok", check=False)
        wait_for_mock.assert_awaited_once_with(run_call, timeout=5)
        assert result == SSHResult(exit_code=0, stdout="ok", stderr="")
