"""Tests for SSHHost controller (health probing)."""

from unittest.mock import AsyncMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshhost import sshhost_probe


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


class TestChooseHostPrefersReady:
    @pytest.mark.asyncio
    async def test_choose_host_prefers_ready(self):
        """_choose_host should prefer hosts with status.ready == True."""
        from unittest.mock import MagicMock

        from capi_provider_ssh.controllers.sshmachine import _choose_host

        spec = {
            "hostSelector": {
                "matchLabels": {"role": "control-plane"},
            },
        }
        # host-a is unchecked (no status.ready), host-b is ready
        hosts = {
            "items": [
                {
                    "metadata": {
                        "name": "host-a",
                        "resourceVersion": "10",
                        "labels": {"role": "control-plane"},
                    },
                    "spec": {
                        "address": "10.0.0.1",
                        "user": "root",
                        "sshKeyRef": {"name": "k", "key": "value"},
                        "consumerRef": {},
                    },
                    "status": {},
                },
                {
                    "metadata": {
                        "name": "host-b",
                        "resourceVersion": "11",
                        "labels": {"role": "control-plane"},
                    },
                    "spec": {
                        "address": "10.0.0.2",
                        "user": "root",
                        "sshKeyRef": {"name": "k", "key": "value"},
                        "consumerRef": {},
                    },
                    "status": {"ready": True},
                },
            ],
        }
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = hosts
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(spec, "m1", "default", patch_obj)

        assert result is True
        # Should pick host-b (ready) over host-a (unchecked)
        assert patch_obj["spec"]["address"] == "10.0.0.2"
        assert patch_obj["spec"]["hostRef"] == "default/host-b"

    @pytest.mark.asyncio
    async def test_choose_host_falls_back_to_unchecked(self):
        """If no hosts are ready, _choose_host should still pick unchecked hosts."""
        from unittest.mock import MagicMock

        from capi_provider_ssh.controllers.sshmachine import _choose_host

        spec = {
            "hostSelector": {
                "matchLabels": {"role": "worker"},
            },
        }
        hosts = {
            "items": [
                {
                    "metadata": {
                        "name": "host-w1",
                        "resourceVersion": "20",
                        "labels": {"role": "worker"},
                    },
                    "spec": {
                        "address": "10.0.1.1",
                        "user": "root",
                        "sshKeyRef": {"name": "k", "key": "value"},
                        "consumerRef": {},
                    },
                    "status": {},
                },
            ],
        }
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = hosts
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(spec, "m1", "default", patch_obj)

        assert result is True
        assert patch_obj["spec"]["address"] == "10.0.1.1"
