"""Tests for SSHMachine controller."""

import asyncio
import re
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import kopf
import pytest
import yaml

from capi_provider_ssh.controllers.sshmachine import (
    _RECONCILE_LOCK_HOLDER,
    BOOTSTRAP_SENTINEL_HIT_OUTPUT,
    BOOTSTRAP_SUCCESS_SENTINEL_PATH,
    _acquire_distributed_reconcile_lock,
    _bootstrap_execution_command,
    _build_reconcile_lock_holder,
    _classify_bootstrap_failure,
    _classify_kubelet_not_ready,
    _detect_bootstrap_format,
    _get_reconcile_lock,
    _has_machine_owner,
    _inject_external_etcd_into_bootstrap_data,
    _inject_provider_id_into_bootstrap_data,
    _is_already_provisioned,
    _normalize_external_etcd,
    _post_bootstrap_readiness_command,
    _prepare_bootstrap_script,
    _release_distributed_reconcile_lock,
    sshmachine_reconcile,
    sshmachine_reconcile_timer,
)
from capi_provider_ssh.ssh import SSHResult


@pytest.fixture(autouse=True)
def bootstrap_unit_boundaries(monkeypatch):
    """Keep renderer/diagnostic unit tests independent of inventory and transport.

    test_lifecycle_contract exercises these boundaries together with persistent
    API semantics, and Kind/SSH tests exercise real servers without these mocks.
    """
    from capi_provider_ssh.controllers import sshmachine as module

    def binding(spec, status, name, namespace, uid, patch):
        return {
            "address": spec.get("address"),
            "port": spec.get("port", 22),
            "user": spec.get("user", "root"),
            "sshKeyRef": spec.get("sshKeyRef", {}),
            "sshHostKeyRef": {"name": "test-trust"},
            "machineUID": uid,
        }

    @asynccontextmanager
    async def operation(*args, **kwargs):
        yield SimpleNamespace(check=AsyncMock())

    async def bootstrap(conn, uid, path, command, **kwargs):
        return await conn.execute(command)

    monkeypatch.setattr(module, "durable_bootstrap", bootstrap)
    monkeypatch.setattr(module, "set_host_phase", lambda *args: None)
    monkeypatch.setattr(module, "bind_machine", binding)
    monkeypatch.setattr(module, "host_operation", operation)
    monkeypatch.setattr(module, "_ensure_bootstrap_ownership", AsyncMock())
    monkeypatch.setattr(module, "read_known_hosts", lambda *args: "verified-test-host")
    monkeypatch.setattr(module, "is_paused", lambda spec, meta, ns: bool(spec.get("paused")))
    monkeypatch.setattr(module, "owned_command", lambda uid, command, **kwargs: command)
    monkeypatch.setattr(module, "_read_current_sshmachine", lambda *args: {"metadata": {}, "spec": {}})


def _kubeadm_docs(bootstrap):
    """Read the actual embedded YAML so tests check types, not pretty printing."""
    if bootstrap.startswith("#cloud-config"):
        payload = next(
            item["content"]
            for item in yaml.safe_load(bootstrap)["write_files"]
            if item["path"] == "/run/kubeadm/kubeadm.yaml"
        )
    else:
        match = re.search(r"<<'([^']+)'[^\n]*\n(.*?)\n\1", bootstrap, re.DOTALL)
        assert match, bootstrap
        payload = match.group(2)
    return {doc["kind"]: doc for doc in yaml.safe_load_all(payload)}


def _assert_provider_id(bootstrap, expected):
    docs = _kubeadm_docs(bootstrap)
    node = docs.get("InitConfiguration", docs.get("JoinConfiguration"))["nodeRegistration"]
    assert {"name": "provider-id", "value": expected} in node["kubeletExtraArgs"]


def _assert_external_etcd(bootstrap):
    cluster = _kubeadm_docs(bootstrap)["ClusterConfiguration"]
    assert cluster["etcd"]["external"] == {
        "endpoints": ["https://10.0.0.10:2379", "https://10.0.0.11:2379"],
        "caFile": "/etc/kubernetes/pki/etcd-external/ca.crt",
        "certFile": "/etc/kubernetes/pki/etcd-external/client.crt",
        "keyFile": "/etc/kubernetes/pki/etcd-external/client.key",
    }
    args = {arg["name"]: arg["value"] for arg in cluster["apiServer"]["extraArgs"]}
    assert args["etcd-servers"] == "https://10.0.0.10:2379,https://10.0.0.11:2379"
    assert args["etcd-cafile"] == cluster["etcd"]["external"]["caFile"]
    assert args["etcd-certfile"] == cluster["etcd"]["external"]["certFile"]
    assert args["etcd-keyfile"] == cluster["etcd"]["external"]["keyFile"]


def _conditions_by_type(status: dict) -> dict[str, dict]:
    return {condition["type"]: condition for condition in status.get("conditions", [])}


@pytest.fixture(autouse=True)
def distributed_lock_success_for_handlers():
    """Keep existing reconcile/delete tests focused by defaulting distributed lock to success."""
    with (
        patch("capi_provider_ssh.controllers.sshmachine._acquire_distributed_reconcile_lock", return_value=True),
        patch("capi_provider_ssh.controllers.sshmachine._release_distributed_reconcile_lock", return_value=True),
    ):
        yield


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


class TestDistributedReconcileLock:
    def test_build_reconcile_lock_holder_prefers_pod_name(self):
        with (
            patch.dict(
                "os.environ",
                {"POD_NAME": "provider-pod|a", "HOSTNAME": "provider-host"},
                clear=True,
            ),
            patch("capi_provider_ssh.controllers.sshmachine.socket.gethostname", return_value="socket-host"),
        ):
            assert _build_reconcile_lock_holder() == "provider-pod_a"

    def test_build_reconcile_lock_holder_uses_hostname_fallback(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("capi_provider_ssh.controllers.sshmachine.socket.gethostname", return_value="socket-host"),
        ):
            assert _build_reconcile_lock_holder() == "socket-host"

    def test_acquire_sets_annotation_when_unlocked(self):
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {
                "resourceVersion": "42",
                "annotations": {},
            },
        }

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            assert _acquire_distributed_reconcile_lock("default", "m1") is True

        mock_api.patch_namespaced_custom_object.assert_called_once()
        patch_body = mock_api.patch_namespaced_custom_object.call_args.kwargs["body"]
        lock_value = patch_body["metadata"]["annotations"]["infrastructure.cluster.x-k8s.io/reconcile-lock"]
        holder, raw_expires = lock_value.rsplit("|", 1)
        assert holder == _RECONCILE_LOCK_HOLDER
        assert int(raw_expires) > int(time.time())

    def test_acquire_returns_false_when_another_holder_lock_is_active(self):
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {
                "resourceVersion": "42",
                "annotations": {
                    "infrastructure.cluster.x-k8s.io/reconcile-lock": f"other-holder|{int(time.time()) + 120}",
                },
            },
        }

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            assert _acquire_distributed_reconcile_lock("default", "m1") is False

        mock_api.patch_namespaced_custom_object.assert_not_called()

    def test_acquire_reclaims_expired_lock(self):
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {
                "resourceVersion": "42",
                "annotations": {
                    "infrastructure.cluster.x-k8s.io/reconcile-lock": "other-holder|1",
                },
            },
        }

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            assert _acquire_distributed_reconcile_lock("default", "m1") is True

        mock_api.patch_namespaced_custom_object.assert_called_once()

    def test_acquire_reclaims_lock_when_same_holder_and_not_expired(self):
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {
                "resourceVersion": "42",
                "annotations": {
                    "infrastructure.cluster.x-k8s.io/reconcile-lock": f"pod-a|{int(time.time()) + 120}",
                },
            },
        }

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
                return_value=mock_api,
            ),
            patch("capi_provider_ssh.controllers.sshmachine._RECONCILE_LOCK_HOLDER", "pod-a"),
        ):
            assert _acquire_distributed_reconcile_lock("default", "m1") is True

        mock_api.patch_namespaced_custom_object.assert_called_once()

    def test_release_refuses_when_lock_is_owned_by_other_holder(self):
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "metadata": {
                "resourceVersion": "43",
                "annotations": {
                    "infrastructure.cluster.x-k8s.io/reconcile-lock": f"other-holder|{int(time.time()) + 120}",
                },
            },
        }

        with patch(
            "capi_provider_ssh.controllers.sshmachine.kubernetes.client.CustomObjectsApi",
            return_value=mock_api,
        ):
            assert _release_distributed_reconcile_lock("default", "m1") is False

        mock_api.patch_namespaced_custom_object.assert_not_called()


class TestBootstrapSentinelCommand:
    def test_bootstrap_execution_command_includes_guard_and_touch(self):
        cmd = _bootstrap_execution_command()
        assert BOOTSTRAP_SUCCESS_SENTINEL_PATH in cmd
        assert BOOTSTRAP_SENTINEL_HIT_OUTPUT in cmd
        assert f"touch {BOOTSTRAP_SUCCESS_SENTINEL_PATH}" in cmd
        assert "chmod 0700 /var/lib/capi-provider-ssh/bootstrap.sh && /var/lib/capi-provider-ssh/bootstrap.sh" in cmd

    def test_post_bootstrap_readiness_command_checks_kubelet(self):
        cmd = _post_bootstrap_readiness_command()
        assert "systemctl is-active --quiet kubelet" in cmd
        assert "systemctl command not found on host" in cmd


class TestBootstrapFailureClassification:
    def test_classify_detects_reset_from_stderr(self):
        result = SSHResult(exit_code=2, stdout="", stderr="[reset] failed to reset node")
        reason, phase, message, stderr_excerpt = _classify_bootstrap_failure(result, "#!/bin/bash\necho bootstrap")
        assert reason == "BootstrapResetFailed"
        assert phase == "reset"
        assert "exit 2" in message
        assert "failed to reset node" in stderr_excerpt

    def test_classify_falls_back_to_bootstrap_script_phase(self):
        result = SSHResult(exit_code=1, stdout="", stderr="command failed")
        reason, phase, message, stderr_excerpt = _classify_bootstrap_failure(
            result, "#!/bin/bash\nkubeadm join 10.0.0.1:6443"
        )
        assert reason == "BootstrapJoinFailed"
        assert phase == "join"
        assert "join phase" in message
        assert stderr_excerpt == "command failed"

    def test_classify_redacts_sensitive_kubeadm_flags(self):
        stderr = (
            "kubeadm join 10.0.0.1:6443 "
            "--token abc.def "
            "--discovery-token-ca-cert-hash sha256:deadbeef "
            "--certificate-key 0123456789abcdef"
        )
        result = SSHResult(exit_code=1, stdout="", stderr=stderr)
        _, _, message, stderr_excerpt = _classify_bootstrap_failure(result, "#!/bin/bash\nkubeadm join 10.0.0.1:6443")
        assert "[REDACTED]" in message
        assert "abc.def" not in message
        assert "sha256:deadbeef" not in message
        assert "0123456789abcdef" not in message
        assert "[REDACTED]" in stderr_excerpt

    def test_classify_uses_generic_reason_when_phase_unknown(self):
        result = SSHResult(exit_code=3, stdout="", stderr="bootstrap failed without phase markers")
        reason, phase, message, _ = _classify_bootstrap_failure(result, "#!/bin/bash\necho bootstrap")
        assert reason == "BootstrapFailed"
        assert phase == "unknown"
        assert "Bootstrap execution failed" in message

    def test_classify_kubelet_not_ready(self):
        result = SSHResult(exit_code=32, stdout="", stderr="inactive")
        reason, message = _classify_kubelet_not_ready(result)
        assert reason == "KubeletNotReady"
        assert "Bootstrap completed, but kubelet is not ready" in message
        assert "inactive" in message


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
        conditions = _conditions_by_type(patch_obj["status"])
        assert conditions["Ready"]["reason"] == "WaitingForMachineOwner"
        assert conditions["InfrastructureReady"]["status"] == "False"
        assert conditions["BootstrapExecSucceeded"]["status"] == "False"

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
        assert patch_obj["status"]["ready"] is True
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
        assert patch_obj["status"]["ready"] is True
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
            mock_conn.execute.side_effect = [
                SSHResult(exit_code=0, stdout="ok", stderr=""),
                SSHResult(exit_code=0, stdout="active", stderr=""),
            ]
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
            assert patch_obj["status"]["initialization"]["provisioned"] is True
            assert patch_obj["status"]["ready"] is True
            assert patch_obj["spec"]["providerID"] == "ssh://100.64.0.10"
            assert patch_obj["status"]["addresses"][0]["address"] == "100.64.0.10"
            assert patch_obj["status"]["failureReason"] is None
            assert mock_conn.execute.await_count == 2
            bootstrap_cmd = mock_conn.execute.call_args_list[0][0][0]
            readiness_cmd = mock_conn.execute.call_args_list[1][0][0]
            assert BOOTSTRAP_SUCCESS_SENTINEL_PATH in bootstrap_cmd
            assert BOOTSTRAP_SENTINEL_HIT_OUTPUT in bootstrap_cmd
            assert "systemctl is-active --quiet kubelet" in readiness_cmd

    @pytest.mark.asyncio
    async def test_bootstrap_with_explicit_ssh_strategy_runs_readiness_check(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        spec = {**sshmachine_spec, "bootstrapCheckStrategy": "ssh"}
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = [
            SSHResult(exit_code=0, stdout="ok", stderr=""),
            SSHResult(exit_code=0, stdout="active", stderr=""),
        ]
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
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        assert patch_obj["status"]["ready"] is True
        assert mock_conn.execute.await_count == 2
        readiness_cmd = mock_conn.execute.call_args_list[1][0][0]
        assert "systemctl is-active --quiet kubelet" in readiness_cmd

    @pytest.mark.asyncio
    async def test_bootstrap_with_none_strategy_skips_readiness_check(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        spec = {**sshmachine_spec, "bootstrapCheckStrategy": "none"}
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
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        assert patch_obj["status"]["ready"] is True
        assert mock_conn.execute.await_count == 1
        conditions = _conditions_by_type(patch_obj["status"])
        assert conditions["BootstrapExecSucceeded"]["status"] == "True"
        assert conditions["BootstrapCheckSkipped"]["reason"] == "StrategyNone"

    @pytest.mark.asyncio
    async def test_invalid_bootstrap_check_strategy_sets_invalid_configuration_status(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        spec = {**sshmachine_spec, "bootstrapCheckStrategy": "invalid"}
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            with pytest.raises(kopf.PermanentError, match="spec.bootstrapCheckStrategy must be one of: ssh, none"):
                await sshmachine_reconcile(
                    spec=spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )

        read_bootstrap.assert_not_called()
        assert patch_obj["status"]["failureReason"] == "InvalidConfiguration"
        assert patch_obj["status"]["ready"] is False
        conditions = _conditions_by_type(patch_obj["status"])
        assert conditions["BootstrapExecSucceeded"]["status"] == "False"

    @pytest.mark.asyncio
    async def test_bootstrap_sentinel_short_circuit_logs_skip(self, sshmachine_spec, sshmachine_meta_with_owner):
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = [
            SSHResult(exit_code=0, stdout=f"{BOOTSTRAP_SENTINEL_HIT_OUTPUT}\n", stderr=""),
            SSHResult(exit_code=0, stdout="active", stderr=""),
        ]
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
            patch("capi_provider_ssh.controllers.sshmachine.logger") as mock_logger,
        ):
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m-sentinel",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
        assert patch_obj["status"]["initialization"]["provisioned"] is True
        assert any(
            "bootstrap sentinel already present" in call.args[0]
            for call in mock_logger.info.call_args_list
            if call.args
        )

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
            assert patch_obj["status"]["failureReason"] == "BootstrapJoinFailed"
            assert patch_obj["status"]["bootstrapDiagnostics"]["phase"] == "join"
            assert patch_obj["status"]["bootstrapDiagnostics"]["exitCode"] == 1
            assert patch_obj["status"]["bootstrapDiagnostics"]["stderrExcerpt"] == "error"
            assert "Bootstrap join phase failed" in patch_obj["status"]["failureMessage"]

    @pytest.mark.asyncio
    async def test_bootstrap_success_with_kubelet_not_ready_sets_not_ready_status(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = [
            SSHResult(exit_code=0, stdout="ok", stderr=""),
            SSHResult(exit_code=32, stdout="", stderr="inactive"),
        ]
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
            with pytest.raises(kopf.TemporaryError, match="Post-bootstrap readiness check failed"):
                await sshmachine_reconcile(
                    spec=sshmachine_spec,
                    status={},
                    name="m1",
                    namespace="default",
                    meta=sshmachine_meta_with_owner,
                    patch=patch_obj,
                )

        assert patch_obj["status"]["initialization"]["provisioned"] is False
        assert patch_obj["status"]["failureReason"] == "KubeletNotReady"
        assert "Bootstrap completed, but kubelet is not ready" in patch_obj["status"]["failureMessage"]
        conditions = _conditions_by_type(patch_obj["status"])
        assert conditions["Ready"]["reason"] == "KubeletNotReady"
        assert conditions["InfrastructureReady"]["status"] == "False"
        assert conditions["BootstrapExecSucceeded"]["status"] == "True"
        assert conditions["Bootstrapped"]["type"] == "Bootstrapped"

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
        assert patch_obj["status"]["ready"] is True

    @pytest.mark.asyncio
    async def test_reconcile_injects_provider_id_into_kubeadm_cloud_config(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        cloud_config_bootstrap = """#cloud-config
write_files:
- path: /run/kubeadm/kubeadm.yaml
  owner: root:root
  permissions: '0600'
  content: |
    apiVersion: kubeadm.k8s.io/v1beta4
    kind: JoinConfiguration
    nodeRegistration:
      name: worker-0
runcmd:
- kubeadm join --config /run/kubeadm/kubeadm.yaml
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
                name="m-providerid",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )

        uploaded_script = mock_conn.upload.call_args[0][0]
        _assert_provider_id(uploaded_script, "ssh://100.64.0.10")
        assert patch_obj["status"]["ready"] is True

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
        waiting_conditions = _conditions_by_type(waiting_patch["status"])
        assert waiting_conditions["Ready"]["reason"] == "WaitingForMachineOwner"

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
        assert recover_patch["status"]["ready"] is True
        assert recover_patch["spec"]["providerID"] == "ssh://100.64.0.10"

    @pytest.mark.asyncio
    async def test_timer_skips_already_provisioned_machine(self, sshmachine_spec, sshmachine_meta_with_owner):
        spec_with_provider = {**sshmachine_spec, "providerID": "ssh://100.64.0.10"}
        status = {
            "initialization": {"provisioned": True},
            "ready": True,
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile_timer(
                spec=spec_with_provider,
                status=status,
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=patch_obj,
            )
        read_bootstrap.assert_not_called()
        assert patch_obj["status"]["ready"] is True
        assert "metadata" not in patch_obj

    @pytest.mark.asyncio
    async def test_timer_keeps_ready_field_in_patch_even_when_annotation_exists(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        spec_with_provider = {**sshmachine_spec, "providerID": "ssh://100.64.0.10"}
        status = {
            "initialization": {"provisioned": True},
            "ready": True,
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        meta_with_ready_ownership = {
            **sshmachine_meta_with_owner,
            "annotations": {"infrastructure.alpininsight.ai/status-ready-owned": "true"},
        }
        with patch(
            "capi_provider_ssh.controllers.sshmachine._read_bootstrap_data",
            new_callable=AsyncMock,
        ) as read_bootstrap:
            patch_obj = kopf.Patch({})
            await sshmachine_reconcile_timer(
                spec=spec_with_provider,
                status=status,
                name="m1",
                namespace="default",
                meta=meta_with_ready_ownership,
                patch=patch_obj,
            )
        read_bootstrap.assert_not_called()
        assert patch_obj["status"]["ready"] is True
        assert "metadata" not in patch_obj

    @pytest.mark.asyncio
    async def test_timer_skips_provisioned_machine_when_ready_false(self, sshmachine_spec, sshmachine_meta_with_owner):
        status = {
            "initialization": {"provisioned": True},
            "ready": False,
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
        assert patch_obj["status"]["ready"] is True
        assert patch_obj["spec"]["providerID"] == "ssh://100.64.0.10"
        conditions = _conditions_by_type(patch_obj["status"])
        assert conditions["Ready"]["status"] == "True"
        assert conditions["InfrastructureReady"]["status"] == "True"
        assert conditions["BootstrapExecSucceeded"]["status"] == "True"

    @pytest.mark.asyncio
    async def test_timer_backfills_missing_providerid_and_ready_on_provisioned_machine(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
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
        assert patch_obj["status"]["ready"] is True
        assert patch_obj["spec"]["providerID"] == "ssh://100.64.0.10"

    @pytest.mark.asyncio
    async def test_waiting_reconcile_refreshes_live_state_and_skips_bootstrap(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        event_meta = {**sshmachine_meta_with_owner, "uid": "uid-race-refresh"}
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
            "metadata": event_meta,
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
                        meta=event_meta,
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
    async def test_reconcile_refreshes_live_state_without_wait_and_skips_stale_bootstrap(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        event_meta = {**sshmachine_meta_with_owner, "uid": "uid-race-no-wait"}
        latest = {
            "spec": sshmachine_spec,
            "status": {
                "initialization": {"provisioned": True},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
            "metadata": event_meta,
        }
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
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m-race-no-wait-flag",
                namespace="default",
                meta=event_meta,
                patch=kopf.Patch({}),
            )
        read_bootstrap.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconcile_skips_when_live_object_missing(self, sshmachine_spec, sshmachine_meta_with_owner):
        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_current_sshmachine",
                return_value=None,
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._sshmachine_reconcile_impl",
                new_callable=AsyncMock,
            ) as reconcile_impl,
        ):
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m-stale-missing",
                namespace="default",
                meta={**sshmachine_meta_with_owner, "uid": "uid-old"},
                patch=kopf.Patch({}),
            )
        reconcile_impl.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reconcile_skips_when_event_uid_differs_from_live_uid(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        latest = {
            "spec": sshmachine_spec,
            "status": {},
            "metadata": {**sshmachine_meta_with_owner, "uid": "uid-live"},
        }

        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._read_current_sshmachine",
                return_value=latest,
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._sshmachine_reconcile_impl",
                new_callable=AsyncMock,
            ) as reconcile_impl,
        ):
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m-stale-uid",
                namespace="default",
                meta={**sshmachine_meta_with_owner, "uid": "uid-old"},
                patch=kopf.Patch({}),
            )
        reconcile_impl.assert_not_awaited()

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

    @pytest.mark.asyncio
    async def test_reconcile_requeues_when_distributed_lock_is_held(
        self,
        sshmachine_spec,
        sshmachine_meta_with_owner,
    ):
        with (
            patch(
                "capi_provider_ssh.controllers.sshmachine._acquire_distributed_reconcile_lock",
                return_value=False,
            ),
            patch(
                "capi_provider_ssh.controllers.sshmachine._sshmachine_reconcile_impl",
                new_callable=AsyncMock,
            ) as reconcile_impl,
            pytest.raises(kopf.TemporaryError, match="distributed reconcile lock"),
        ):
            await sshmachine_reconcile(
                spec=sshmachine_spec,
                status={},
                name="m1",
                namespace="default",
                meta=sshmachine_meta_with_owner,
                patch=kopf.Patch({}),
            )
        reconcile_impl.assert_not_awaited()


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
        # Should NOT set providerID or mark machine provisioned
        assert "providerID" not in patch_obj.get("spec", {})
        assert patch_obj["status"]["initialization"]["provisioned"] is False
        assert patch_obj["status"]["ready"] is False

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
        assert len(conditions) == 4
        by_type = _conditions_by_type(patch_obj["status"])
        assert by_type["Ready"]["status"] == "False"
        assert by_type["InfrastructureReady"]["status"] == "False"
        assert by_type["BootstrapExecSucceeded"]["status"] == "False"
        assert by_type["DryRunValidated"]["reason"] == "PreflightPassed"
        assert "SSH to 100.64.0.10" in by_type["DryRunValidated"]["message"]
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
  extraArgs: []
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
            "endpoints": ["https://10.0.0.10:2379", "https://10.0.0.11:2379"],
            "ca_file": "/etc/kubernetes/pki/etcd-external/ca.crt",
            "cert_file": "/etc/kubernetes/pki/etcd-external/client.crt",
            "key_file": "/etc/kubernetes/pki/etcd-external/client.key",
        }
        patched, changed = _inject_external_etcd_into_bootstrap_data(bootstrap, external)
        assert changed is True
        _assert_external_etcd(patched)

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
      extraArgs: []
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
            "endpoints": ["https://10.0.0.10:2379", "https://10.0.0.11:2379"],
            "ca_file": "/etc/kubernetes/pki/etcd-external/ca.crt",
            "cert_file": "/etc/kubernetes/pki/etcd-external/client.crt",
            "key_file": "/etc/kubernetes/pki/etcd-external/client.key",
        }
        patched, changed = _inject_external_etcd_into_bootstrap_data(bootstrap, external)
        assert changed is True
        assert patched.startswith("#cloud-config")
        _assert_external_etcd(patched)

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

    def test_inject_provider_id_into_shell_bootstrap_data(self):
        bootstrap = """#!/bin/bash
cat > /run/kubeadm/kubeadm.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
nodeRegistration:
  name: cp-0
EOF
kubeadm init --config /run/kubeadm/kubeadm.yaml
"""
        patched, changed = _inject_provider_id_into_bootstrap_data(bootstrap, "ssh://10.0.0.10")
        assert changed is True
        _assert_provider_id(patched, "ssh://10.0.0.10")

    def test_inject_provider_id_into_cloud_config_bootstrap_data(self):
        bootstrap = """#cloud-config
write_files:
- path: /run/kubeadm/kubeadm.yaml
  owner: root:root
  permissions: '0600'
  content: |
    apiVersion: kubeadm.k8s.io/v1beta4
    kind: JoinConfiguration
    nodeRegistration:
      name: w-0
runcmd:
- kubeadm join --config /run/kubeadm/kubeadm.yaml
"""
        patched, changed = _inject_provider_id_into_bootstrap_data(bootstrap, "ssh://10.0.0.20")
        assert changed is True
        assert patched.startswith("#cloud-config")
        _assert_provider_id(patched, "ssh://10.0.0.20")


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
  extraArgs: []
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
                "capi_provider_ssh.controllers.sshmachine._external_etcd_files_script",
                new_callable=AsyncMock,
                return_value="# staged certificates\n",
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
        _assert_external_etcd(uploaded_script)
        _assert_provider_id(uploaded_script, "ssh://100.64.0.10")
