"""Tests for SSHMachine controller."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import kopf
import pytest

from capi_provider_ssh.controllers.sshmachine import (
    _choose_host,
    _detect_bootstrap_format,
    _get_reconcile_lock,
    _has_machine_owner,
    _inject_external_etcd_into_bootstrap_data,
    _is_already_provisioned,
    _normalize_external_etcd,
    _prepare_bootstrap_script,
    _release_host,
    sshmachine_delete,
    sshmachine_reboot,
    sshmachine_reconcile,
    sshmachine_reconcile_timer,
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
        assert _is_already_provisioned(status, "ssh://10.0.0.1") is True

    def test_provisioned_without_ready_condition(self):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [],
        }
        assert _is_already_provisioned(status, "ssh://10.0.0.1") is True


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
    async def test_already_provisioned_skips_when_ready_false(self, sshmachine_spec, sshmachine_meta_with_owner):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "False"}],
        }
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status=status,
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
        read_bootstrap.assert_not_called()
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

    @pytest.mark.asyncio
    async def test_successful_bootstrap_with_cloud_config(self, sshmachine_spec, sshmachine_meta_with_owner):
        cloud_config_bootstrap = """## template: jinja
#cloud-config
write_files:
- path: /etc/kubernetes/bootstrap-marker
  owner: root:root
  permissions: '0644'
  content: |
    marker=true
runcmd:
- echo bootstrap
- [kubeadm, join, 10.0.0.1:6443]
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
                return_value=cloud_config_bootstrap,
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
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        uploaded_script = mock_conn.upload.call_args[0][0]
        assert "#cloud-config" not in uploaded_script
        assert "cat <<'__CAPI_BOOTSTRAP_FILE_0__' > /etc/kubernetes/bootstrap-marker" in uploaded_script
        assert "kubeadm join 10.0.0.1:6443" in uploaded_script
        assert patch_obj["status"]["initialization"]["provisioned"] is True

    @pytest.mark.asyncio
    async def test_timer_recovers_after_owner_reference_appears(self, sshmachine_spec, sshmachine_meta_with_owner):
        waiting_patch = kopf.Patch({})
        await sshmachine_reconcile(
            spec=sshmachine_spec,
            status={},
            name="m1",
            namespace="default",
            meta={},
            patch=waiting_patch,
        )
        assert waiting_patch["status"]["conditions"][0]["reason"] == "WaitingForMachineOwner"

        mock_conn = AsyncMock()
        mock_conn.execute.return_value = SSHResult(exit_code=0, stdout="ok", stderr="")
        mock_conn.upload = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
                new_callable=AsyncMock,
                return_value="#!/bin/bash\necho bootstrap",
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
            recover_patch = kopf.Patch({})
            await sshmachine_reconcile_timer(
                spec=sshmachine_spec,
                status=waiting_patch.get("status", {}),
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=recover_patch,
            )

        assert recover_patch["status"]["initialization"]["provisioned"] is True
        assert recover_patch["spec"]["providerID"] == "ssh://100.64.0.10"

    @pytest.mark.asyncio
    async def test_timer_skips_already_provisioned_machine(self, sshmachine_spec, sshmachine_meta_with_owner):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile_timer(
                spec=sshmachine_spec,
                status=status,
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
        read_bootstrap.assert_not_called()

    @pytest.mark.asyncio
    async def test_timer_skips_provisioned_machine_when_ready_false(self, sshmachine_spec, sshmachine_meta_with_owner):
        status = {
            "initialization": {"provisioned": True},
            "conditions": [{"type": "Ready", "status": "False"}],
        }
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile_timer(
                spec=sshmachine_spec,
                status=status,
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
        read_bootstrap.assert_not_called()

    @pytest.mark.asyncio
    async def test_waiting_reconcile_refreshes_live_state_and_skips_bootstrap(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        name = "m-race-refresh"
        namespace = "default"
        lock = _get_reconcile_lock(namespace, name)
        await lock.acquire()

        latest = {
            "spec": sshmachine_spec,
            "status": {
                "initialization": {"provisioned": True},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
            "metadata": sshmachine_meta_with_owner,
        }

        task = None
        try:
            with (
                patch(
                    "capi_provider_ssh.controllers.sshmachine._read_current_sshmachine",
                    return_value=latest,
                ),
                patch(
                    "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
                    new_callable=AsyncMock,
                ) as read_bootstrap,
            ):
                patch_obj = kopf.Patch({})
                task = asyncio.create_task(
                    sshmachine_reconcile(
                        spec=sshmachine_spec,
                        status={},
                        name=name,
                        namespace=namespace,
                        meta=sshmachine_meta_with_owner,
                        patch=patch_obj,
                    ),
                )
                await asyncio.sleep(0)
                lock.release()
                await task
                read_bootstrap.assert_not_called()
        finally:
            if task is not None and not task.done():
                await task
            if lock.locked():
                lock.release()

    @pytest.mark.asyncio
    async def test_handler_and_timer_reconcile_are_serialized(self, sshmachine_spec, sshmachine_meta_with_owner):
        name = "m-race-serialized"
        namespace = "default"
        active = 0
        max_active = 0

        async def fake_impl(**_kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_current_sshmachine",
                return_value=None,
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._sshmachine_reconcile_impl",
                new=AsyncMock(side_effect=fake_impl),
            ) as reconcile_impl,
        ):
            await asyncio.gather(
                sshmachine_reconcile(
                    spec=sshmachine_spec,
                    status={},
                    name=name,
                    namespace=namespace,
                    meta=sshmachine_meta_with_owner,
                    patch=kopf.Patch({}),
                ),
                sshmachine_reconcile_timer(
                    spec=sshmachine_spec,
                    status={},
                    name=name,
                    namespace=namespace,
                    meta=sshmachine_meta_with_owner,
                    patch=kopf.Patch({}),
                ),
            )

        assert reconcile_impl.await_count == 2
        assert max_active == 1


class TestSSHMachineDryRun:
    @pytest.mark.asyncio
    async def test_dryrun_validates_without_bootstrap_execution(self, sshmachine_meta_with_owner):
        """Dry-run should connect via SSH but not upload or execute the bootstrap script."""
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
            "dryRun": True,
        }
        mock_conn = AsyncMock()
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
            await sshmachine_reconcile(
                spec=spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        # Should NOT have uploaded or executed anything
        mock_conn.upload.assert_not_called()
        mock_conn.execute.assert_not_called()
        # Should NOT set providerID or provisioned
        assert "providerID" not in patch_obj.get("spec", {})
        assert "initialization" not in patch_obj.get("status", {})

    @pytest.mark.asyncio
    async def test_dryrun_sets_condition(self, sshmachine_meta_with_owner):
        """Dry-run should set a DryRunValidated condition."""
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
            "dryRun": True,
        }
        mock_conn = AsyncMock()
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
            await sshmachine_reconcile(
                spec=spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        conditions = patch_obj["status"]["conditions"]
        assert len(conditions) == 1
        assert conditions[0]["type"] == "DryRunValidated"
        assert conditions[0]["reason"] == "PreflightPassed"
        assert "SSH to 100.64.0.10" in conditions[0]["message"]
        assert patch_obj["status"]["failureReason"] is None
        assert patch_obj["status"]["failureMessage"] is None

    @pytest.mark.asyncio
    async def test_dryrun_fails_on_ssh_unreachable(self, sshmachine_meta_with_owner):
        """Dry-run should propagate SSH connection failures."""
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
            "dryRun": True,
        }
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
                side_effect=ConnectionRefusedError("Connection refused"),
            ),
        ):
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.TemporaryError, match="Dry-run SSH failed"):
                await sshmachine_reconcile(
                    spec=spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )

        assert patch_obj["status"]["failureReason"] == "DryRunSSHFailed"


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
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "host-2", "resourceVersion": "12"},
            "spec": {"consumerRef": {"kind": "SSHMachine", "name": "m1", "namespace": "default"}},
        }

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
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "existing"}}
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
    async def test_unchecked_host_preferred_over_failed_host(self, sshmachine_spec_with_hostselector):
        """Unknown health state should be preferred over explicitly failed hosts."""
        hosts = {
            "items": [
                {
                    "metadata": {
                        "name": "a-failed",
                        "resourceVersion": "20",
                        "labels": {"role": "control-plane", "cluster": "hetzner-staging"},
                    },
                    "spec": {
                        "address": "10.0.0.20",
                        "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
                        "consumerRef": {},
                    },
                    "status": {"ready": False},
                },
                {
                    "metadata": {
                        "name": "z-unknown",
                        "resourceVersion": "21",
                        "labels": {"role": "control-plane", "cluster": "hetzner-staging"},
                    },
                    "spec": {
                        "address": "10.0.0.21",
                        "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
                        "consumerRef": {},
                    },
                },
            ],
        }
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = hosts
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "existing"}}
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(sshmachine_spec_with_hostselector, "m1", "default", patch_obj)
            assert result is True
            assert patch_obj["spec"]["hostRef"] == "default/z-unknown"
            assert patch_obj["spec"]["address"] == "10.0.0.21"

    @pytest.mark.asyncio
    async def test_hostselector_takes_precedence_over_address(self, sshhost_items):
        """hostSelector mode must win even if address is pre-set in spec."""
        spec = {
            "address": "10.0.0.10",
            "hostSelector": {
                "matchLabels": {
                    "role": "control-plane",
                    "cluster": "hetzner-staging",
                },
            },
        }
        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = sshhost_items
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "existing"}}
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(spec, "m1", "default", patch_obj)
            assert result is True
            assert patch_obj["spec"]["address"] == "65.21.157.69"
            assert patch_obj["spec"]["hostRef"] == "default/host-2"

    @pytest.mark.asyncio
    async def test_reclaims_orphaned_host(self, sshmachine_spec_with_hostselector):
        """Orphaned SSHHost claims should be cleared and then reused."""
        host = {
            "items": [
                {
                    "metadata": {
                        "name": "host-9",
                        "resourceVersion": "20",
                        "labels": {"role": "control-plane", "cluster": "hetzner-staging"},
                    },
                    "spec": {
                        "address": "65.21.157.200",
                        "user": "root",
                        "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
                        "consumerRef": {"kind": "SSHMachine", "name": "gone", "namespace": "default"},
                    },
                },
            ],
        }
        refreshed_host = {
            "metadata": {
                "name": "host-9",
                "resourceVersion": "21",
                "labels": {"role": "control-plane", "cluster": "hetzner-staging"},
            },
            "spec": {
                "address": "65.21.157.200",
                "user": "root",
                "sshKeyRef": {"name": "hetzner-ssh-key", "key": "value"},
                "consumerRef": {},
            },
        }

        mock_api = MagicMock()
        mock_api.list_namespaced_custom_object.return_value = host
        import kubernetes as k8s

        mock_api.get_namespaced_custom_object.side_effect = [
            k8s.client.ApiException(status=404),  # orphan check for gone machine
            refreshed_host,  # refresh host after clearing stale claim
        ]
        mock_api.patch_namespaced_custom_object.return_value = None

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            patch_obj = kopf.Patch({})
            result = await _choose_host(sshmachine_spec_with_hostselector, "m1", "default", patch_obj)
            assert result is True
            assert patch_obj["spec"]["hostRef"] == "default/host-9"
            assert patch_obj["spec"]["address"] == "65.21.157.200"
            assert mock_api.patch_namespaced_custom_object.call_count == 2
            first_call = mock_api.patch_namespaced_custom_object.call_args_list[0][1]["body"]
            second_call = mock_api.patch_namespaced_custom_object.call_args_list[1][1]["body"]
            assert first_call["spec"]["consumerRef"] == {}
            assert second_call["spec"]["consumerRef"]["name"] == "m1"

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
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "other"}}

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
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "host-2", "resourceVersion": "12"},
            "spec": {"consumerRef": {"kind": "SSHMachine", "name": "m1", "namespace": "default"}},
        }

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
    async def test_release_skips_foreign_claim(self):
        """Release must not clear a host that is claimed by another machine."""
        spec = {"hostRef": "default/host-2"}
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "host-2", "resourceVersion": "12"},
            "spec": {"consumerRef": {"kind": "SSHMachine", "name": "other", "namespace": "default"}},
        }

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            await _release_host(spec, "m1", "default")
            mock_api.patch_namespaced_custom_object.assert_not_called()

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
        mock_api.get_namespaced_custom_object.side_effect = k8s.client.ApiException(status=404)

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            # Should not raise
            await _release_host(spec, "m1", "default")
            mock_api.patch_namespaced_custom_object.assert_not_called()


class TestExternalEtcdConfig:
    def test_normalize_external_etcd_valid(self):
        spec = {
            "externalEtcd": {
                "endpoints": ["https://10.0.0.10:2379", "https://10.0.0.11:2379"],
                "caCertRef": {"name": "etcd-ca"},
                "clientCertRef": {"name": "etcd-client-cert"},
                "clientKeyRef": {"name": "etcd-client-key"},
            },
        }
        cfg = _normalize_external_etcd(spec)
        assert cfg is not None
        assert cfg["servers"] == "https://10.0.0.10:2379,https://10.0.0.11:2379"
        assert cfg["ca_file"] == "/etc/kubernetes/pki/etcd-external/ca.crt"

    def test_normalize_external_etcd_invalid_endpoints(self):
        spec = {
            "externalEtcd": {
                "endpoints": [],
                "caCertRef": {"name": "etcd-ca"},
                "clientCertRef": {"name": "etcd-client-cert"},
                "clientKeyRef": {"name": "etcd-client-key"},
            },
        }
        with pytest.raises(kopf.PermanentError, match="externalEtcd.endpoints"):
            _normalize_external_etcd(spec)

    def test_detect_bootstrap_format_cloud_config(self):
        bootstrap = """## template: jinja
#cloud-config
runcmd:
- echo ok
"""
        assert _detect_bootstrap_format(bootstrap) == "cloud-config"

    def test_prepare_bootstrap_script_renders_cloud_config(self):
        bootstrap = """#cloud-config
write_files:
- path: /etc/kubernetes/bootstrap-marker
  owner: root:root
  permissions: '0644'
  content: |
    marker=true
runcmd:
- [echo, bootstrap]
"""
        script, bootstrap_format = _prepare_bootstrap_script(bootstrap)
        assert bootstrap_format == "cloud-config"
        assert "cat <<'__CAPI_BOOTSTRAP_FILE_0__' > /etc/kubernetes/bootstrap-marker" in script
        assert "chmod 0644 /etc/kubernetes/bootstrap-marker" in script
        assert "chown root:root /etc/kubernetes/bootstrap-marker" in script
        assert "echo bootstrap" in script

    def test_inject_external_etcd_into_bootstrap_data(self):
        bootstrap = """#!/bin/bash
cat > /run/kubeadm/kubeadm.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
apiServer:
  extraArgs: {}
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
nodeRegistration:
  name: cp-0
EOF
kubeadm init --config /run/kubeadm/kubeadm.yaml
"""
        external = {
            "servers": "https://10.0.0.10:2379,https://10.0.0.11:2379",
            "ca_file": "/etc/kubernetes/pki/etcd-external/ca.crt",
            "cert_file": "/etc/kubernetes/pki/etcd-external/client.crt",
            "key_file": "/etc/kubernetes/pki/etcd-external/client.key",
        }
        patched, changed = _inject_external_etcd_into_bootstrap_data(bootstrap, external)
        assert changed is True
        assert "etcd-servers: https://10.0.0.10:2379,https://10.0.0.11:2379" in patched
        assert "etcd-cafile: /etc/kubernetes/pki/etcd-external/ca.crt" in patched
        assert "etcd-certfile: /etc/kubernetes/pki/etcd-external/client.crt" in patched
        assert "etcd-keyfile: /etc/kubernetes/pki/etcd-external/client.key" in patched

    def test_inject_external_etcd_into_cloud_config_bootstrap_data(self):
        bootstrap = """#cloud-config
write_files:
- path: /run/kubeadm/kubeadm.yaml
  owner: root:root
  permissions: '0600'
  content: |
    apiVersion: kubeadm.k8s.io/v1beta4
    kind: ClusterConfiguration
    apiServer:
      extraArgs: {}
    ---
    apiVersion: kubeadm.k8s.io/v1beta4
    kind: InitConfiguration
    nodeRegistration:
      name: cp-0
runcmd:
- kubeadm init --config /run/kubeadm/kubeadm.yaml
"""
        external = {
            "servers": "https://10.0.0.10:2379,https://10.0.0.11:2379",
            "ca_file": "/etc/kubernetes/pki/etcd-external/ca.crt",
            "cert_file": "/etc/kubernetes/pki/etcd-external/client.crt",
            "key_file": "/etc/kubernetes/pki/etcd-external/client.key",
        }
        patched, changed = _inject_external_etcd_into_bootstrap_data(bootstrap, external)
        assert changed is True
        assert patched.startswith("#cloud-config")
        assert "etcd-servers: https://10.0.0.10:2379,https://10.0.0.11:2379" in patched

    def test_inject_external_etcd_requires_cluster_configuration(self):
        bootstrap = """#!/bin/bash
echo "no kubeadm yaml here"
"""
        external = {
            "servers": "https://10.0.0.10:2379",
            "ca_file": "/etc/kubernetes/pki/etcd-external/ca.crt",
            "cert_file": "/etc/kubernetes/pki/etcd-external/client.crt",
            "key_file": "/etc/kubernetes/pki/etcd-external/client.key",
        }
        with pytest.raises(kopf.PermanentError, match="no kubeadm ClusterConfiguration"):
            _inject_external_etcd_into_bootstrap_data(bootstrap, external)


class TestSSHMachineReboot:
    @pytest.mark.asyncio
    async def test_reboot_success_sets_status(self):
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
        }
        patch_obj = kopf.Patch({})
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
            await sshmachine_reboot(
                old=None,
                new="2026-02-20T16:00:00Z",
                spec=spec,
                name="m1",
                namespace="default",
                patch=patch_obj,
            )

        status = patch_obj["status"]["remediation"]["reboot"]
        assert status["lastRequestedAt"] == "2026-02-20T16:00:00Z"
        assert status["success"] is True

    @pytest.mark.asyncio
    async def test_reboot_missing_address_requeues(self):
        spec = {
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
        }
        patch_obj = kopf.Patch({})
        with pytest.raises(kopf.TemporaryError, match="waiting for address/sshKeyRef"):
            await sshmachine_reboot(
                old=None,
                new="2026-02-20T16:10:00Z",
                spec=spec,
                name="m1",
                namespace="default",
                patch=patch_obj,
            )
        status = patch_obj["status"]["remediation"]["reboot"]
        assert status["success"] is False

    @pytest.mark.asyncio
    async def test_reboot_key_read_failure_requeues(self):
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
        }
        patch_obj = kopf.Patch({})
        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                side_effect=ConnectionError("apiserver unavailable"),
            ),
            pytest.raises(kopf.TemporaryError, match="failed to read SSH key for reboot remediation"),
        ):
            await sshmachine_reboot(
                old=None,
                new="2026-02-20T16:15:00Z",
                spec=spec,
                name="m1",
                namespace="default",
                patch=patch_obj,
            )
        status = patch_obj["status"]["remediation"]["reboot"]
        assert status["success"] is False


class TestSSHMachineExternalEtcdReconcile:
    @pytest.mark.asyncio
    async def test_external_etcd_bootstrap_injection_and_cert_upload(self, sshmachine_meta_with_owner):
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
            "externalEtcd": {
                "endpoints": ["https://10.0.0.10:2379", "https://10.0.0.11:2379"],
                "caCertRef": {"name": "etcd-ca"},
                "clientCertRef": {"name": "etcd-client-cert"},
                "clientKeyRef": {"name": "etcd-client-key"},
            },
        }
        bootstrap = """#!/bin/bash
cat > /run/kubeadm/kubeadm.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
apiServer:
  extraArgs: {}
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
nodeRegistration:
  name: cp-0
EOF
kubeadm init --config /run/kubeadm/kubeadm.yaml
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
                return_value=bootstrap,
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_ssh_key",
                new_callable=AsyncMock,
                return_value="fake-key",
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._upload_external_etcd_certs",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_upload_certs,
            patch(
                "capi_provider_ssh.controllers.sshmachine.SSHClient.connect",
                new_callable=AsyncMock,
                return_value=mock_conn,
            ),
        ):
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        mock_upload_certs.assert_called_once()
        uploaded_script = mock_conn.upload.call_args[0][0]
        assert "etcd-servers: https://10.0.0.10:2379,https://10.0.0.11:2379" in uploaded_script

    @pytest.mark.asyncio
    async def test_reboot_command_failure_requeues(self):
        spec = {
            "address": "100.64.0.10",
            "port": 22,
            "user": "root",
            "sshKeyRef": {"name": "ssh-key-secret", "key": "value"},
        }
        patch_obj = kopf.Patch({})
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = SSHResult(exit_code=1, stdout="", stderr="reboot failed")
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
            pytest.raises(kopf.TemporaryError, match="reboot remediation command failed"),
        ):
            await sshmachine_reboot(
                old=None,
                new="2026-02-20T16:20:00Z",
                spec=spec,
                name="m1",
                namespace="default",
                patch=patch_obj,
            )

        status = patch_obj["status"]["remediation"]["reboot"]
        assert status["success"] is False
