"""Lifecycle regressions with persistent API semantics and controllable SSH outcomes."""

import asyncio
import datetime
from unittest.mock import AsyncMock, Mock

import kopf
import kubernetes
import pytest
import yaml

from capi_provider_ssh import API_GROUP
from capi_provider_ssh.controllers import sshmachine as controller
from capi_provider_ssh.inventory import bind_machine, consumer_ref
from capi_provider_ssh.operations import HostLease, host_operation
from capi_provider_ssh.ssh import SSHClient, SSHResult
from tests.fake_api import ObjectStore

BOOT_A = "00000000-0000-0000-0000-000000000001"
BOOT_B = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def api(monkeypatch):
    store = ObjectStore()
    for cls in ("CustomObjectsApi", "CoreV1Api", "CoordinationV1Api"):
        monkeypatch.setattr(kubernetes.client, cls, lambda: store)
    return store


@pytest.fixture
def ssh(monkeypatch):
    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    conn.__aexit__.return_value = False
    conn.events = []
    conn.boot_id = BOOT_A
    conn.reset_code = 0
    conn.bootstrap_code = 0
    conn.reboot_error = None

    async def execute(command, **kwargs):
        if "kubeadm reset -f" in command:
            conn.events.append("reset")
            return SSHResult(conn.reset_code, "", "reset failure" if conn.reset_code else "")
        if "CAPI_EXIT=" in command:
            message = "kubeadm join failed" if conn.bootstrap_code else "ok"
            return SSHResult(0, f"CAPI_EXIT={conn.bootstrap_code}\n{message}", "")
        if "cat /proc/sys/kernel/random/boot_id" in command:
            conn.events.append("boot-id")
            return SSHResult(0, conn.boot_id, "")
        if "nohup sh" in command:
            conn.events.append("reboot")
            if conn.reboot_error:
                raise conn.reboot_error
        elif "chmod 0700 /var/lib/capi-provider-ssh/bootstrap-" in command:
            conn.events.append("bootstrap")
            return SSHResult(0, "submitted", "")
        else:
            conn.events.append("check")
        return SSHResult(0, "ok", "")

    conn.execute.side_effect = execute
    monkeypatch.setattr(SSHClient, "connect", AsyncMock(return_value=conn))
    return conn


async def reconcile(api, obj, *, delete=False):
    obj = api.current(obj)
    patch = kopf.Patch()
    try:
        await controller.sshmachine_reconcile(
            obj["spec"],
            obj.get("status", {}),
            obj["metadata"]["name"],
            obj["metadata"]["namespace"],
            obj["metadata"],
            patch,
            action="delete" if delete else "reconcile",
        )
    finally:
        args = dict(
            group=API_GROUP,
            version="v1beta1",
            namespace=obj["metadata"]["namespace"],
            plural="sshmachines",
            name=obj["metadata"]["name"],
        )
        if patch.get("spec"):
            api.patch_namespaced_custom_object(**args, body={"spec": dict(patch.spec)})
        if patch.get("status"):
            api.patch_namespaced_custom_object_status(**args, body={"status": dict(patch.status)})
    return api.current(obj)


def host(api, name="host-a", *, ready=True, port=2222, status=None, ref=None, labels=None):
    return api.add(
        "sshhosts",
        name,
        {
            "address": f"{name}.test",
            "port": port,
            "sshKeyRef": {"name": "key"},
            "sshHostKeyRef": {"name": "trust"},
            **({"consumerRef": ref} if ref else {}),
        },
        status={"ready": ready, **(status or {})},
        meta={"labels": labels or {"role": "worker"}},
    )


def pool_machine(api, name="machine-a"):
    return api.machine(name, spec={"hostSelector": {"matchLabels": {"role": "worker"}}})


def raw(api, obj, plural="sshmachines"):
    return api.objects[API_GROUP, plural, obj["metadata"]["namespace"], obj["metadata"]["name"]]


@pytest.mark.parametrize("drift", ["health", "labels", "list-order"])
async def test_existing_allocation_never_moves_to_spare(api, ssh, drift):
    machine = pool_machine(api)
    old = host(api)
    machine = await reconcile(api, machine)
    spare = host(api, "aaa-spare")
    if drift == "health":
        raw(api, old, "sshhosts")["status"]["ready"] = False
    if drift == "labels":
        raw(api, old, "sshhosts")["metadata"]["labels"] = {"role": "retired"}
    ssh.events.clear()
    result = await reconcile(api, machine)
    assert result["spec"]["hostRef"] == "test/host-a"
    assert result["spec"]["providerID"] == "ssh://host-a.test"
    assert result["status"]["addresses"][0]["address"] == "host-a.test"
    assert "bootstrap" not in ssh.events
    assert not api.current(spare, "sshhosts")["spec"].get("consumerRef")


async def test_claim_recovers_after_crash_before_binding_persistence(api, ssh):
    machine = pool_machine(api)
    own = host(api, "z-old", ready=False, ref=consumer_ref("machine-a", "test", machine["metadata"]["uid"]))
    host(api, "a-spare")
    result = await reconcile(api, machine)
    assert result["spec"]["hostRef"] == "test/z-old"
    assert api.current(own, "sshhosts")["status"]["inUse"] is True


@pytest.mark.parametrize("host_ref_written", [False, True])
async def test_delete_recovers_an_unstarted_uid_claim_without_ssh(api, ssh, host_ref_written):
    machine = pool_machine(api)
    claimed = host(api, "claimed", ref=consumer_ref("machine-a", "test", machine["metadata"]["uid"]))
    if host_ref_written:
        raw(api, machine)["spec"]["hostRef"] = "test/claimed"
    await reconcile(api, machine, delete=True)
    assert not api.current(claimed, "sshhosts")["spec"].get("consumerRef")
    SSHClient.connect.assert_not_awaited()


@pytest.mark.parametrize("kind", ["machine-uid", "host-uid", "address", "port", "providerID"])
async def test_allocated_identity_changes_fail_closed(api, ssh, kind):
    machine = pool_machine(api)
    h = host(api)
    machine = await reconcile(api, machine)
    target = raw(api, machine)
    if kind == "machine-uid":
        target["metadata"]["uid"] = "replacement-uid"
    elif kind == "host-uid":
        raw(api, h, "sshhosts")["metadata"]["uid"] = "replacement-host"
    else:
        target["spec"][kind] = 23 if kind == "port" else "changed"
    ssh.events.clear()
    with pytest.raises((kopf.PermanentError, kopf.TemporaryError)):
        await reconcile(api, machine)
    assert not ssh.events


@pytest.mark.parametrize("phase", ["Cleaning", "Quarantined"])
async def test_unclaimed_but_unclean_host_is_not_allocated(api, ssh, phase):
    machine = pool_machine(api)
    host(api, status={"phase": phase})
    with pytest.raises(kopf.TemporaryError, match="No available"):
        await reconcile(api, machine)
    assert not ssh.events


async def test_orphaned_or_legacy_claim_is_never_automatically_reused(api, ssh):
    machine = pool_machine(api)
    host(api, ref={"kind": "SSHMachine", "name": "missing", "namespace": "test"})
    with pytest.raises(kopf.TemporaryError):
        await reconcile(api, machine)
    assert not ssh.events


async def test_claim_port_and_inuse_persist(api, ssh):
    machine = pool_machine(api)
    h = host(api, port=2200)
    result = await reconcile(api, machine)
    assert result["spec"]["port"] == 2200
    assert result["status"]["allocation"]["port"] == 2200
    assert SSHClient.connect.call_args.kwargs["port"] == 2200
    assert api.current(h, "sshhosts")["status"]["inUse"] is True
    assert api.current(h, "sshhosts")["spec"]["consumerRef"]["uid"] == machine["metadata"]["uid"]


async def test_claim_conflict_tries_another_available_host(api, ssh):
    machine = pool_machine(api)
    host(api, "a-host")
    host(api, "b-host")
    api.claim_conflicts = 1
    result = await reconcile(api, machine)
    assert result["spec"]["hostRef"] == "test/b-host"


async def test_status_persistence_failure_prevents_remote_execution(api, ssh):
    machine = api.machine()
    api.status_failure = True
    with pytest.raises(kopf.TemporaryError):
        await reconcile(api, machine)
    assert not ssh.events


async def test_cleanup_keeps_claim_until_success(api, ssh):
    machine = pool_machine(api)
    h = host(api)
    machine = await reconcile(api, machine)
    original_execute = ssh.execute.side_effect

    async def check_claim(command, **kwargs):
        if "kubeadm reset" in command:
            current = api.current(h, "sshhosts")
            assert current["status"]["phase"] == "Cleaning"
            assert current["spec"]["consumerRef"]["uid"] == machine["metadata"]["uid"]
            with pytest.raises(kopf.TemporaryError):
                other = pool_machine(api, "other")
                bind_machine(other["spec"], {}, "other", "test", other["metadata"]["uid"], kopf.Patch())
        return await original_execute(command, **kwargs)

    ssh.execute.side_effect = check_claim
    await reconcile(api, machine, delete=True)
    current = api.current(h, "sshhosts")
    assert current["status"]["phase"] == "Available"
    assert current["status"]["inUse"] is False
    assert not current["spec"].get("consumerRef")


async def test_failed_reset_quarantines_and_retry_recovers(api, ssh):
    machine = pool_machine(api)
    h = host(api)
    machine = await reconcile(api, machine)
    ssh.reset_code = 1
    with pytest.raises(kopf.TemporaryError, match="quarantined"):
        await reconcile(api, machine, delete=True)
    assert api.current(h, "sshhosts")["status"]["phase"] == "Quarantined"
    assert api.current(h, "sshhosts")["spec"]["consumerRef"]["uid"] == machine["metadata"]["uid"]
    ssh.reset_code = 0
    await reconcile(api, machine, delete=True)
    assert api.current(h, "sshhosts")["status"]["phase"] == "Available"


async def test_dryrun_create_reboot_delete_never_mutates_host(api, ssh):
    machine = pool_machine(api)
    host(api)
    raw(api, machine)["spec"].update(dryRun=True, remediation={"reboot": {"requestedAt": "2026-09-06T00:00:00Z"}})
    await reconcile(api, machine)
    await reconcile(api, machine, delete=True)
    assert not ssh.events
    ssh.upload.assert_not_called()


async def test_enabling_dryrun_after_bootstrap_does_not_bypass_cleanup(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["dryRun"] = True
    await reconcile(api, machine, delete=True)
    assert "reset" in ssh.events


async def test_partial_bootstrap_is_owned_and_can_be_cleaned(api, ssh):
    machine = api.machine()
    ssh.bootstrap_code = 1
    with pytest.raises(kopf.TemporaryError):
        await reconcile(api, machine)
    assert api.current(machine)["status"]["bootstrapOwnership"]["machineUID"] == machine["metadata"]["uid"]
    await reconcile(api, machine, delete=True)
    assert "reset" in ssh.events


@pytest.mark.parametrize("pause_on", ["infra-annotation", "machine-annotation", "cluster-spec", "cluster-annotation"])
@pytest.mark.parametrize("action", ["bootstrap", "delete", "reboot"])
async def test_capi_pause_blocks_all_remote_actions(api, ssh, pause_on, action):
    machine = api.machine()
    if action != "bootstrap":
        machine = await reconcile(api, machine)
    if action == "reboot":
        raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-06T00:00:00Z"}}
    targets = {
        "infra-annotation": raw(api, machine),
        "machine-annotation": api.objects["cluster.x-k8s.io", "machines", "test", "machine-a"],
        "cluster-spec": api.objects["cluster.x-k8s.io", "clusters", "test", "cluster-a"],
        "cluster-annotation": api.objects["cluster.x-k8s.io", "clusters", "test", "cluster-a"],
    }
    if pause_on == "cluster-spec":
        targets[pause_on]["spec"]["paused"] = True
    else:
        targets[pause_on]["metadata"]["annotations"] = {"cluster.x-k8s.io/paused": ""}
    ssh.events.clear()
    if action == "delete":
        with pytest.raises(kopf.TemporaryError):
            await reconcile(api, machine, delete=True)
    else:
        await reconcile(api, machine)
    assert not ssh.events


async def test_resume_after_cluster_pause_bootstraps_once(api, ssh):
    machine = api.machine()
    cluster = api.objects["cluster.x-k8s.io", "clusters", "test", "cluster-a"]
    cluster["spec"]["paused"] = True
    await reconcile(api, machine)
    cluster["spec"]["paused"] = False
    await reconcile(api, machine)
    await reconcile(api, machine)
    assert ssh.events.count("bootstrap") == 1


async def test_reboot_waits_for_new_boot_id_and_is_not_replayed(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-06T00:00:00Z"}}
    result = await reconcile(api, machine)
    state = result["status"]["remediation"]["reboot"]
    assert state["phase"] == "Submitted" and state["success"] is False
    assert "lastCompletedAt" not in state
    with pytest.raises(kopf.TemporaryError, match="Waiting to observe"):
        await reconcile(api, machine)
    ssh.boot_id = BOOT_B
    result = await reconcile(api, machine)
    assert result["status"]["remediation"]["reboot"]["phase"] == "Succeeded"
    assert ssh.events.count("reboot") == 1


async def test_lost_reboot_response_is_observed_without_resubmission(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-06T00:00:00Z"}}
    ssh.reboot_error = TimeoutError("lost response")
    with pytest.raises(kopf.TemporaryError, match="unknown"):
        await reconcile(api, machine)
    ssh.reboot_error = None
    ssh.boot_id = BOOT_B
    await reconcile(api, machine)
    assert ssh.events.count("reboot") == 1


async def test_reboot_cannot_run_while_machine_lock_is_held(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-06T00:00:00Z"}}
    lock = controller._get_reconcile_lock("test", "machine-a")
    await lock.acquire()
    task = asyncio.create_task(reconcile(api, machine))
    await asyncio.sleep(0)
    assert not task.done() and "reboot" not in ssh.events
    lock.release()
    await task
    assert ssh.events.count("reboot") == 1


async def test_lease_serializes_same_target_across_machine_namespaces(api):
    binding = {"address": "HOST.test.", "port": 2222}
    async with host_operation(binding, "uid-a"):
        with pytest.raises(kopf.TemporaryError, match="Another operation"):
            async with host_operation({**binding, "address": "host.test"}, "uid-b"):
                pytest.fail("a second operation acquired the same target")


def test_expired_lease_can_fail_over_but_old_holder_cannot_release_it(api):
    old = HostLease("host.test", 22, "old")
    new = HostLease("host.test", 22, "new")
    assert old.acquire()
    lease = next(iter(api.leases.values()))
    lease.spec.renew_time -= datetime.timedelta(seconds=120)
    assert new.acquire()
    assert old.renew() is False
    old.release()
    assert next(iter(api.leases.values())).spec.holder_identity == new.holder


@pytest.mark.parametrize("kind", ["InitConfiguration", "JoinConfiguration"])
@pytest.mark.parametrize("version", ["v1beta3", "v1beta4"])
@pytest.mark.parametrize("present", [True, False])
def test_kubeadm_argument_shapes_are_versioned_and_idempotent(kind, version, present):
    args = {"node-ip": "192.0.2.10"} if version == "v1beta3" else [{"name": "node-ip", "value": "192.0.2.10"}]
    doc = {
        "apiVersion": f"kubeadm.k8s.io/{version}",
        "kind": kind,
        "nodeRegistration": {"kubeletExtraArgs": args} if present else {},
    }
    rendered, _, _ = controller._patch_provider_id_in_kubeadm_yaml(yaml.safe_dump(doc), "ssh://192.0.2.10")
    patched = yaml.safe_load(rendered)["nodeRegistration"]["kubeletExtraArgs"]
    assert isinstance(patched, dict if version == "v1beta3" else list)
    second, _, changed = controller._patch_provider_id_in_kubeadm_yaml(rendered, "ssh://192.0.2.10")
    assert second == rendered and changed is False


def test_unknown_kubeadm_version_is_rejected():
    with pytest.raises(kopf.PermanentError, match="Unsupported"):
        controller._patch_provider_id_in_kubeadm_yaml(
            "apiVersion: kubeadm.k8s.io/v99\nkind: JoinConfiguration\n", "ssh://host"
        )


@pytest.mark.parametrize("version", ["v1beta3", "v1beta4"])
def test_external_etcd_control_plane_join_uses_existing_cluster_config(version):
    config = {"apiVersion": f"kubeadm.k8s.io/{version}", "kind": "JoinConfiguration", "controlPlane": {}}
    payload = yaml.safe_dump(config)
    result, recognized, changed = controller._patch_external_etcd_in_kubeadm_yaml(payload, {})
    assert recognized and not changed and yaml.safe_load(result) == config


@pytest.mark.parametrize("failure", ["changed-holder", "api-unavailable"])
@pytest.mark.timeout(3)
async def test_lease_loss_interrupts_local_work_without_releasing_a_new_owner(api, monkeypatch, failure):
    monkeypatch.setattr("capi_provider_ssh.operations.LEASE_SECONDS", 0.04)

    def lose_lease(self):
        current = next(iter(api.leases.values()))
        current.spec.holder_identity = "replacement-holder"
        if failure == "api-unavailable":
            raise kubernetes.client.ApiException(status=503)
        return False

    monkeypatch.setattr(HostLease, "renew", lose_lease)
    with pytest.raises(kopf.TemporaryError, match="Lost host Lease"):
        async with host_operation({"address": "host", "port": 22}, "uid"):
            await asyncio.sleep(1)
            pytest.fail("local work continued after losing its Lease")
    assert next(iter(api.leases.values())).spec.holder_identity == "replacement-holder"


@pytest.mark.parametrize("stage", ["read", "create", "replace"])
async def test_lease_api_failure_never_starts_a_remote_operation(api, ssh, monkeypatch, stage):
    if stage == "replace":
        old = HostLease("host", 22, "old")
        assert old.acquire()
        next(iter(api.leases.values())).spec.renew_time -= datetime.timedelta(seconds=120)
    method = f"{stage}_namespaced_lease"
    failure = Mock(side_effect=kubernetes.client.ApiException(status=503))
    monkeypatch.setattr(api, method, failure)
    with pytest.raises(kopf.TemporaryError, match="Cannot acquire"):
        async with host_operation({"address": "host", "port": 22}, "uid"):
            await ssh.execute("must not run")
    failure.assert_called_once()
    ssh.execute.assert_not_awaited()


@pytest.mark.parametrize("stage", ["create", "replace"])
async def test_lease_cas_conflict_does_not_enter_the_operation(api, monkeypatch, stage):
    if stage == "replace":
        old = HostLease("host", 22, "old")
        assert old.acquire()
        next(iter(api.leases.values())).spec.renew_time -= datetime.timedelta(seconds=120)
    failure = Mock(side_effect=kubernetes.client.ApiException(status=409))
    monkeypatch.setattr(api, f"{stage}_namespaced_lease", failure)
    with pytest.raises(kopf.TemporaryError, match="Another operation"):
        async with host_operation({"address": "host", "port": 22}, "uid"):
            pytest.fail("conflicting claim entered the operation")
    failure.assert_called_once()
    if stage == "replace":
        assert next(iter(api.leases.values())).spec.holder_identity == old.holder


@pytest.mark.timeout(3)
async def test_external_cancellation_propagates_and_releases_own_lease(api):
    entered = asyncio.Event()

    async def work():
        async with host_operation({"address": "host", "port": 22}, "uid"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert next(iter(api.leases.values())).spec.holder_identity is None


async def test_release_failure_keeps_expiring_claim_without_masking_operation_error(api, monkeypatch):
    release = Mock(side_effect=kubernetes.client.ApiException(status=503))
    monkeypatch.setattr(HostLease, "release", release)
    with pytest.raises(ValueError, match="operation failed"):
        async with host_operation({"address": "host", "port": 22}, "uid") as lease:
            raise ValueError("operation failed")
    release.assert_called_once()
    assert next(iter(api.leases.values())).spec.holder_identity == lease.holder


@pytest.mark.parametrize("plural", ["machines", "clusters"])
@pytest.mark.parametrize("status_code", [404, 403, 503])
async def test_unreadable_capi_owner_chain_blocks_bootstrap(api, ssh, monkeypatch, plural, status_code):
    machine = api.machine()
    original = api.get_namespaced_custom_object

    def unavailable(*args, **kwargs):
        if kwargs.get("plural") == plural:
            raise kubernetes.client.ApiException(status=status_code)
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "get_namespaced_custom_object", unavailable)
    if status_code == 404:
        await reconcile(api, machine)
    else:
        with pytest.raises(kopf.TemporaryError, match="pause state"):
            await reconcile(api, machine)
    SSHClient.connect.assert_not_awaited()
    assert not api.current(machine)["status"].get("bootstrapOwnership")


async def test_recreated_capi_owner_blocks_bootstrap(api, ssh):
    machine = api.machine()
    api.objects["cluster.x-k8s.io", "machines", "test", "machine-a"]["metadata"]["uid"] = "new-owner"
    with pytest.raises(kopf.TemporaryError, match="owner UID changed"):
        await reconcile(api, machine)
    SSHClient.connect.assert_not_awaited()


@pytest.mark.parametrize("field", ["machineUID", "address", "port", "hostUID"])
async def test_cleanup_refuses_unverified_bootstrap_ownership_and_keeps_claim(api, ssh, field):
    machine = pool_machine(api)
    allocated = host(api)
    machine = await reconcile(api, machine)
    raw(api, machine)["status"]["bootstrapOwnership"][field] = 9999 if field == "port" else "different"
    ssh.events.clear()
    SSHClient.connect.reset_mock()
    with pytest.raises(kopf.TemporaryError, match="ownership"):
        await reconcile(api, machine, delete=True)
    SSHClient.connect.assert_not_awaited()
    assert api.current(allocated, "sshhosts")["spec"]["consumerRef"]["uid"] == machine["metadata"]["uid"]
    assert not ssh.events


async def test_delete_with_ambiguous_unstarted_claims_retains_both_for_recovery(api, ssh):
    machine = pool_machine(api)
    ref = consumer_ref("machine-a", "test", machine["metadata"]["uid"])
    allocated = [host(api, name, ref=ref) for name in ("first", "second")]
    with pytest.raises(kopf.TemporaryError, match="Multiple UID claims"):
        await reconcile(api, machine, delete=True)
    SSHClient.connect.assert_not_awaited()
    assert all(api.current(item, "sshhosts")["spec"]["consumerRef"] == ref for item in allocated)


async def test_completed_cleanup_retry_only_releases_claim_without_repeating_reset(api, ssh, monkeypatch):
    machine = pool_machine(api)
    allocated = host(api)
    machine = await reconcile(api, machine)
    from capi_provider_ssh import lifecycle

    with monkeypatch.context() as patcher:
        patcher.setattr(lifecycle, "release_host", Mock())
        await reconcile(api, machine, delete=True)
    assert api.current(machine)["status"]["cleanup"]["phase"] == "Succeeded"
    assert api.current(allocated, "sshhosts")["spec"]["consumerRef"]
    SSHClient.connect.reset_mock()
    await reconcile(api, machine, delete=True)
    SSHClient.connect.assert_not_awaited()
    assert ssh.events.count("reset") == 1
    assert not api.current(allocated, "sshhosts")["spec"].get("consumerRef")


async def test_unobserved_reboot_deadline_never_replays_same_request(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-07T00:00:00Z"}}
    await reconcile(api, machine)
    state = raw(api, machine)["status"]["remediation"]["reboot"]
    state["startedAt"] = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)).isoformat()
    for _ in range(2):
        result = await reconcile(api, machine)
        assert result["status"]["remediation"]["reboot"]["phase"] == "Unknown"
        assert result["status"]["remediation"]["reboot"]["success"] is False
    assert ssh.events.count("reboot") == 1


async def test_new_reboot_request_cannot_overlap_a_submitted_request(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-07T00:00:00Z"}}
    await reconcile(api, machine)
    raw(api, machine)["spec"]["remediation"]["reboot"]["requestedAt"] = "2026-09-07T00:01:00Z"
    with pytest.raises(kopf.TemporaryError, match="previous reboot is still in progress"):
        await reconcile(api, machine)
    assert api.current(machine)["status"]["remediation"]["reboot"]["lastRequestedAt"] == "2026-09-07T00:00:00Z"
    assert ssh.events.count("reboot") == 1


async def test_cleanup_waits_for_pending_reboot_without_submitting_another(api, ssh):
    machine = pool_machine(api)
    allocated = host(api)
    machine = await reconcile(api, machine)
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-07T00:00:00Z"}}
    await reconcile(api, machine)
    with pytest.raises(kopf.TemporaryError, match="Waiting to observe"):
        await reconcile(api, machine, delete=True)
    assert "reset" not in ssh.events
    assert api.current(allocated, "sshhosts")["spec"]["consumerRef"]
    ssh.boot_id = BOOT_B
    with pytest.raises(kopf.TemporaryError, match="Cleanup waits"):
        await reconcile(api, machine, delete=True)
    await reconcile(api, machine, delete=True)
    assert ssh.events.count("reboot") == 1 and ssh.events.count("reset") == 1
    assert not api.current(allocated, "sshhosts")["spec"].get("consumerRef")


async def test_invalid_boot_identity_prevents_reboot_submission(api, ssh):
    machine = await reconcile(api, api.machine())
    raw(api, machine)["spec"]["remediation"] = {"reboot": {"requestedAt": "2026-09-07T00:00:00Z"}}
    ssh.boot_id = "unverifiable"
    with pytest.raises(kopf.TemporaryError, match="host boot identity"):
        await reconcile(api, machine)
    assert "reboot" not in ssh.events
