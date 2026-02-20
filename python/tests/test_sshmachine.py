"""Tests for SSHMachine controller."""

from unittest.mock import AsyncMock, MagicMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshmachine import (
    _choose_host,
    _has_machine_owner,
    _is_already_provisioned,
    _release_host,
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

    @pytest.mark.asyncio
    async def test_delete_releases_host(self, sshmachine_spec):
        """Delete must release claimed SSHHost back to pool."""
        spec_with_host = {**sshmachine_spec, "hostRef": "default/host-2"}
        mock_api = MagicMock()

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
                return_value=mock_api,
            ),
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
            await sshmachine_delete(spec=spec_with_host, name="m1", namespace="default")
            # Verify SSHHost was patched to clear consumerRef
            mock_api.patch_namespaced_custom_object.assert_called_once()
            call_kwargs = mock_api.patch_namespaced_custom_object.call_args
            assert call_kwargs[1]["name"] == "host-2"
            body = call_kwargs[1]["body"]
            assert body["spec"]["consumerRef"] == {}
            assert body["status"]["inUse"] is False


class TestChooseHost:
    @pytest.mark.asyncio
    async def test_direct_address_returns_true(self, sshmachine_spec):
        """If address is already set, chooseHost does nothing."""
        patch_obj = kopf.Patch({})
        result = await _choose_host(sshmachine_spec, "m1", "default", patch_obj)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_address_no_selector_raises(self):
        """Missing both address and hostSelector is a permanent error."""
        patch_obj = kopf.Patch({})
        with pytest.raises(kopf.PermanentError, match="Either address or hostSelector"):
            await _choose_host({}, "m1", "default", patch_obj)

    @pytest.mark.asyncio
    async def test_claims_first_available_host(self, sshmachine_spec_with_hostselector, sshhost_items):
        """Should claim host-2 (first unclaimed CP host)."""
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = sshhost_items
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(sshmachine_spec_with_hostselector, "m1", "default", patch_obj)
            assert result is True
            # Should have claimed host-2 (host-1 is already claimed, host-3 is worker)
            assert patch_obj["spec"]["address"] == "65.21.157.69"
            assert patch_obj["spec"]["hostRef"] == "default/host-2"
            assert patch_obj["spec"]["sshKeyRef"]["name"] == "hetzner-ssh-key"
            # SSHHost should have been patched with consumerRef
            mock_api.patch_namespaced_custom_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_available_host_requeues(self, sshmachine_spec_with_hostselector):
        """All hosts claimed -> TemporaryError with delay."""
        all_claimed = {
            "items": [
                {
                    "metadata": {"name": "h1", "labels": {"role": "control-plane", "cluster": "hetzner-staging"}},
                    "spec": {
                        "address": "1.2.3.4",
                        "sshKeyRef": {"name": "k"},
                        "consumerRef": {"kind": "SSHMachine", "name": "other", "namespace": "default"},
                    },
                },
            ],
        }
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = all_claimed

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="No available SSHHost"):
                await _choose_host(sshmachine_spec_with_hostselector, "m1", "default", patch_obj)


class TestReleaseHost:
    @pytest.mark.asyncio
    async def test_release_clears_consumer_ref(self):
        """Release should clear consumerRef on the SSHHost."""
        spec = {"hostRef": "default/host-2"}
        mock_api = MagicMock()

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            await _release_host(spec, "m1", "default")
            mock_api.patch_namespaced_custom_object.assert_called_once()
            body = mock_api.patch_namespaced_custom_object.call_args[1]["body"]
            assert body["spec"]["consumerRef"] == {}
            assert body["status"]["inUse"] is False

    @pytest.mark.asyncio
    async def test_release_no_hostref_is_noop(self):
        """No hostRef means nothing to release."""
        mock_api = MagicMock()
        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            await _release_host({}, "m1", "default")
            mock_api.patch_namespaced_custom_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_missing_host_does_not_raise(self):
        """If SSHHost was already deleted, release should not raise."""
        import kubernetes as k8s

        spec = {"hostRef": "default/host-gone"}
        mock_api = MagicMock()
        mock_api.patch_namespaced_custom_object.side_effect = k8s.client.ApiException(status=404)

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            # Should not raise
            await _release_host(spec, "m1", "default")
