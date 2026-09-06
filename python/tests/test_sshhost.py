"""Tests for SSHHost controller (health probing)."""

from unittest.mock import AsyncMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshhost import sshhost_probe


@pytest.fixture(autouse=True)
def trusted_probe_host(monkeypatch):
    monkeypatch.setattr("capi_provider_ssh.controllers.sshhost.read_known_hosts", lambda *args: "verified-test-host")


class TestSSHHostProbe:
    @pytest.mark.asyncio
    async def test_probe_sets_ready_on_success(self):
        """Successful SSH connection should set status.ready = True."""
        spec = {
            "address": "65.21.157.69",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
        }
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "capi_provider_ssh.controllers.sshhost._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshhost.SSHClient.connect",
                new_callable=AsyncMock,
                return_value=mock_conn,
            ),
        ):
            patch_obj = kopf.Patch({})
            await sshhost_probe(
                spec=spec,
                status={},
                name="host-1",
                namespace="default",
                patch=patch_obj,
            )

        assert patch_obj["status"]["ready"] is True
        assert patch_obj["status"]["lastProbeSuccess"] is True
        assert "lastProbeTime" in patch_obj["status"]
        conditions = patch_obj["status"]["conditions"]
        assert conditions[0]["type"] == "SSHReachable"
        assert conditions[0]["status"] == "True"
        assert conditions[0]["reason"] == "ProbeSucceeded"

    @pytest.mark.asyncio
    async def test_probe_clears_ready_on_failure(self):
        """Failed SSH connection should set status.ready = False."""
        spec = {
            "address": "65.21.157.69",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
        }
        with (
            patch(
                "capi_provider_ssh.controllers.sshhost._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshhost.SSHClient.connect",
                new_callable=AsyncMock,
                side_effect=ConnectionRefusedError("Connection refused"),
            ),
        ):
            patch_obj = kopf.Patch({})
            await sshhost_probe(
                spec=spec,
                status={},
                name="host-1",
                namespace="default",
                patch=patch_obj,
            )

        assert patch_obj["status"]["ready"] is False
        assert patch_obj["status"]["lastProbeSuccess"] is False
        conditions = patch_obj["status"]["conditions"]
        assert conditions[0]["type"] == "SSHReachable"
        assert conditions[0]["status"] == "False"
        assert conditions[0]["reason"] == "ProbeFailed"

    @pytest.mark.asyncio
    async def test_probe_handles_missing_ssh_key(self):
        """SSH key read failure should mark host as not ready."""
        spec = {
            "address": "65.21.157.69",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "missing-key", "key": "value"},
        }
        with patch(
            "capi_provider_ssh.controllers.sshhost._read_ssh_key",
            new_callable=AsyncMock,
            side_effect=Exception("Secret not found"),
        ):
            patch_obj = kopf.Patch({})
            await sshhost_probe(
                spec=spec,
                status={},
                name="host-1",
                namespace="default",
                patch=patch_obj,
            )

        assert patch_obj["status"]["ready"] is False
        assert patch_obj["status"]["lastProbeSuccess"] is False
        conditions = patch_obj["status"]["conditions"]
        assert conditions[0]["reason"] == "SSHKeyReadError"

    @pytest.mark.asyncio
    async def test_probe_skips_missing_address(self):
        """Hosts without address should be silently skipped."""
        spec = {"sshKeyRef": {"name": "key"}}
        patch_obj = kopf.Patch({})
        await sshhost_probe(
            spec=spec,
            status={},
            name="host-bad",
            namespace="default",
            patch=patch_obj,
        )
        # No status changes
        assert "ready" not in patch_obj.get("status", {})
