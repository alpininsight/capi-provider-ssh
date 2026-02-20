"""Integration tests for SSHMachine controller against real K8s API.

These tests call sshmachine_reconcile() and sshmachine_delete() directly
with real K8s objects but mock SSH connections. This validates:
- Real CRD schema (spec fields pass validation)
- Real K8s Secret reads (_read_ssh_key, _read_bootstrap_data)
- Status persistence via K8s API
- Idempotency of the reconciliation loop
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshmachine import (
    sshmachine_delete,
    sshmachine_reconcile,
)
from capi_provider_ssh.ssh import SSHResult
from tests.integration.helpers import create_sshmachine, get_sshmachine

pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]


def _mock_ssh_conn(exit_code: int = 0, stdout: str = "ok", stderr: str = ""):
    """Create a mock SSH connection with configurable command result."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = SSHResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
    mock_conn.upload = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    return mock_conn


class TestSSHMachineProvision:
    """SSHMachine provisioning with real K8s API + mocked SSH."""

    @pytest.mark.asyncio
    async def test_successful_provision(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
        capi_machine_cr,
    ):
        """Create SSHMachine with all prerequisites → reconcile → verify provisioned."""
        spec = {
            "address": "192.168.99.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-provision"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)
        resource = get_sshmachine(custom_api, name, test_namespace)

        mock_conn = _mock_ssh_conn()

        with patch(
            "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
            new_callable=AsyncMock,
            return_value=mock_conn,
        ):
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=resource["spec"],
                status=resource.get("status", {}),
                name=name,
                namespace=test_namespace,
                meta=resource["metadata"],
                patch=patch_obj,
            )

        # Verify reconcile set the correct status
        assert patch_obj["status"]["initialization"]["provisioned"] is True
        assert patch_obj["spec"]["providerID"] == "ssh://192.168.99.10"
        assert patch_obj["status"]["addresses"][0]["address"] == "192.168.99.10"
        assert patch_obj["status"]["failureReason"] is None
        assert patch_obj["status"]["conditions"][0]["reason"] == "Provisioned"

        # Verify SSH was called correctly
        mock_conn.upload.assert_called_once()
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotent_no_replay(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
        capi_machine_cr,
    ):
        """Already-provisioned SSHMachine should skip bootstrap (idempotency)."""
        spec = {
            "address": "192.168.99.11",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-idempotent"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)

        # Simulate already-provisioned status
        already_provisioned_status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "True", "reason": "Provisioned"}],
        }

        resource = get_sshmachine(custom_api, name, test_namespace)

        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=resource["spec"],
            status=already_provisioned_status,
            name=name,
            namespace=test_namespace,
            meta=resource["metadata"],
            patch=patch_obj,
        )

        # Should not touch status -- early return
        assert "initialization" not in patch_obj.get("status", {})


class TestSSHMachinePaused:
    """Paused SSHMachine should skip reconciliation."""

    @pytest.mark.asyncio
    async def test_paused_skips(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
    ):
        """Create paused SSHMachine → reconcile → verify no status changes."""
        spec = {
            "address": "192.168.99.12",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
            "paused": True,
        }
        name = "test-sshmachine-paused"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)
        resource = get_sshmachine(custom_api, name, test_namespace)

        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=resource["spec"],
            status={},
            name=name,
            namespace=test_namespace,
            meta=resource["metadata"],
            patch=patch_obj,
        )

        assert "initialization" not in patch_obj.get("status", {})


class TestSSHMachineNoOwner:
    """SSHMachine without Machine owner should set WaitingForMachineOwner."""

    @pytest.mark.asyncio
    async def test_no_owner_not_ready(
        self,
        custom_api,
        test_namespace,
        ssh_key_secret,
    ):
        """Create SSHMachine without ownerReference → verify not provisioned."""
        spec = {
            "address": "192.168.99.13",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-no-owner"

        create_sshmachine(custom_api, name, test_namespace, spec)
        resource = get_sshmachine(custom_api, name, test_namespace)

        patch_obj = kopf.Patch({})
        await sshmachine_reconcile(
            spec=resource["spec"],
            status={},
            name=name,
            namespace=test_namespace,
            meta=resource["metadata"],
            patch=patch_obj,
        )

        assert patch_obj["status"]["initialization"]["provisioned"] is False
        assert patch_obj["status"]["conditions"][0]["reason"] == "WaitingForMachineOwner"


class TestSSHMachineBootstrapFailure:
    """SSHMachine with SSH bootstrap failure should set failureReason."""

    @pytest.mark.asyncio
    async def test_bootstrap_script_failure(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
        capi_machine_cr,
    ):
        """Bootstrap script returns non-zero → verify BootstrapFailed status."""
        spec = {
            "address": "192.168.99.14",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-fail"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)
        resource = get_sshmachine(custom_api, name, test_namespace)

        mock_conn = _mock_ssh_conn(exit_code=1, stdout="", stderr="bootstrap failed")

        with patch(
            "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
            new_callable=AsyncMock,
            return_value=mock_conn,
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="Bootstrap failed"):
                await sshmachine_reconcile(
                    spec=resource["spec"],
                    status={},
                    name=name,
                    namespace=test_namespace,
                    meta=resource["metadata"],
                    patch=patch_obj,
                )

        assert patch_obj["status"]["failureReason"] == "BootstrapFailed"

    @pytest.mark.asyncio
    async def test_ssh_connection_failure(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
        capi_machine_cr,
    ):
        """SSH connection failure → verify SSHError status."""
        spec = {
            "address": "192.168.99.15",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-ssh-err"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)
        resource = get_sshmachine(custom_api, name, test_namespace)

        with patch(
            "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="SSH error"):
                await sshmachine_reconcile(
                    spec=resource["spec"],
                    status={},
                    name=name,
                    namespace=test_namespace,
                    meta=resource["metadata"],
                    patch=patch_obj,
                )

        assert patch_obj["status"]["failureReason"] == "SSHError"


class TestSSHMachineDelete:
    """SSHMachine deletion should run cleanup and remove finalizer."""

    @pytest.mark.asyncio
    async def test_delete_runs_cleanup(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
    ):
        """Delete SSHMachine → verify kubeadm reset was called via SSH."""
        spec = {
            "address": "192.168.99.16",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-del"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)

        mock_conn = _mock_ssh_conn()

        with patch(
            "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
            new_callable=AsyncMock,
            return_value=mock_conn,
        ):
            await sshmachine_delete(
                spec=spec,
                name=name,
                namespace=test_namespace,
            )

        # Verify cleanup command was called
        mock_conn.execute.assert_called_once()
        cmd = mock_conn.execute.call_args[0][0]
        assert "kubeadm reset -f" in cmd

    @pytest.mark.asyncio
    async def test_delete_ssh_failure_does_not_block(
        self,
        custom_api,
        test_namespace,
        machine_owner_ref,
        ssh_key_secret,
    ):
        """SSH failure during cleanup should not raise (finalizer must always be removed)."""
        spec = {
            "address": "192.168.99.17",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": ssh_key_secret, "key": "value"},
        }
        name = "test-sshmachine-del-fail"

        create_sshmachine(custom_api, name, test_namespace, spec, owner_refs=machine_owner_ref)

        with patch(
            "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("host unreachable"),
        ):
            # Must not raise
            await sshmachine_delete(
                spec=spec,
                name=name,
                namespace=test_namespace,
            )
