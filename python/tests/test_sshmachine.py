"""Tests for SSHMachine controller."""

from unittest.mock import AsyncMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshmachine import (
    _has_machine_owner,
    _is_already_provisioned,
    sshmachine_delete,
    sshmachine_reconcile,
)
from capi_provider_ssh.ssh import SSHResult


class TestHasMachineOwner:
    def test_with_machine_owner(self, sshmachine_meta_with_owner):
        assert _has_machine_owner(sshmachine_meta_with_owner["ownerReferences"]) is True

    def test_without_owner(self):
        assert _has_machine_owner(None) is False

    def test_wrong_kind(self):
        refs = [{"apiVersion": "cluster.x-k8s.io/v1beta1", "kind": "Cluster", "name": "c"}]
        assert _has_machine_owner(refs) is False


class TestIsAlreadyProvisioned:
    def test_provisioned_with_ready(self):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        assert _is_already_provisioned(status, "ssh://10.0.0.1") is True

    def test_not_provisioned(self):
        assert _is_already_provisioned({}, "ssh://10.0.0.1") is False

    def test_provisioned_but_not_ready(self):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "False"}],
        }
        assert _is_already_provisioned(status, "ssh://10.0.0.1") is False


class TestSSHMachineReconcile:
    @pytest.mark.asyncio
    async def test_paused_skips(self, sshmachine_meta_with_owner):
        spec = {**{"address": "10.0.0.1"}, "paused": True}
        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=spec,
            status={},
            name="m1",
            namespace="default",
            meta=sshmachine_meta_with_owner,
            patch=patch_obj,
        )
        assert "initialization" not in patch_obj.get("status", {})

    @pytest.mark.asyncio
    async def test_no_owner_not_ready(self, sshmachine_spec):
        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=sshmachine_spec,
            status={},
            name="m1",
            namespace="default",
            meta={},
            patch=patch_obj,
        )
        assert patch_obj["status"]["initialization"]["provisioned"] is False
        assert patch_obj["status"]["conditions"][0]["reason"] == "WaitingForMachineOwner"

    @pytest.mark.asyncio
    async def test_already_provisioned_skips(self, sshmachine_spec, sshmachine_meta_with_owner):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=sshmachine_spec,
            status=status,
            name="m1",
            namespace="default",
            meta=sshmachine_meta_with_owner,
            patch=patch_obj,
        )
        # Should not modify status (idempotent)
        assert "initialization" not in patch_obj.get("status", {})

    @pytest.mark.asyncio
    async def test_waiting_for_bootstrap_data(self, sshmachine_spec, sshmachine_meta_with_owner):
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
            return_value=None,
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="Bootstrap data not ready"):
                await sshmachine_reconcile(
                    spec=sshmachine_spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )

    @pytest.mark.asyncio
    async def test_missing_ssh_key_ref(self, sshmachine_meta_with_owner):
        spec = {"address": "10.0.0.1"}  # No sshKeyRef
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
            return_value="#!/bin/bash\nkubeadm join ...",
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.PermanentError, match="sshKeyRef.name"):
                await sshmachine_reconcile(
                    spec=spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )

    @pytest.mark.asyncio
    async def test_successful_bootstrap(self, sshmachine_spec, sshmachine_meta_with_owner):
        """Regression: SSHClient.connect() is async, so the controller must use
        ``async with await SSHClient.connect(...)`` (not ``async with SSHClient.connect(...)``).
        Without the ``await``, the coroutine is passed directly to ``__aenter__`` which fails
        with "'coroutine' object does not support the asynchronous context manager protocol".
        """
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = SSHResult(exit_code=0, stdout="ok", stderr="")
        mock_conn.upload = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
                new_callable=AsyncMock,
                return_value="#!/bin/bash\nkubeadm join ...",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                return_value="-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
                new_callable=AsyncMock,
                return_value=mock_conn,
            ),
        ):
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
            assert patch_obj["status"]["initialization"]["provisioned"] is True
            assert patch_obj["spec"]["providerID"] == "ssh://100.64.0.10"
            assert patch_obj["status"]["addresses"][0]["address"] == "100.64.0.10"
            assert patch_obj["status"]["failureReason"] is None

    @pytest.mark.asyncio
    async def test_bootstrap_failure_sets_failure_status(self, sshmachine_spec, sshmachine_meta_with_owner):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = SSHResult(exit_code=1, stdout="", stderr="error")
        mock_conn.upload = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
                new_callable=AsyncMock,
                return_value="#!/bin/bash\nkubeadm join ...",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
                new_callable=AsyncMock,
                return_value=mock_conn,
            ),
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="Bootstrap failed"):
                await sshmachine_reconcile(
                    spec=sshmachine_spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )
            assert patch_obj["status"]["failureReason"] == "BootstrapFailed"


class TestSSHMachineDelete:
    @pytest.mark.asyncio
    async def test_delete_no_address_skips(self):
        """Missing address should not block finalizer."""
        await sshmachine_delete(spec={}, name="m1", namespace="default")

    @pytest.mark.asyncio
    async def test_delete_runs_kubeadm_reset(self, sshmachine_spec):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = SSHResult(exit_code=0, stdout="ok", stderr="")
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
                new_callable=AsyncMock,
                return_value=mock_conn,
            ),
        ):
            await sshmachine_delete(spec=sshmachine_spec, name="m1", namespace="default")
            mock_conn.execute.assert_called_once()
            cmd = mock_conn.execute.call_args[0][0]
            assert "kubeadm reset -f" in cmd

    @pytest.mark.asyncio
    async def test_delete_ssh_failure_does_not_raise(self, sshmachine_spec):
        """SSH cleanup failure must not block finalizer removal."""
        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
                new_callable=AsyncMock,
                side_effect=ConnectionRefusedError("refused"),
            ),
        ):
            # Should not raise
            await sshmachine_delete(spec=sshmachine_spec, name="m1", namespace="default")
