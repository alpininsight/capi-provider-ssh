"""Cross-replica host leases and remote UID fencing for lifecycle operations."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import os
import shlex
import uuid
from contextlib import asynccontextmanager, suppress

import kopf
import kubernetes

from capi_provider_ssh.api_io import request, run_coordination

OWNER_PATH = "/var/lib/capi-provider-ssh/owner"
REMOTE_LOCK = "/var/lib/capi-provider-ssh-operation.lock"
LEASE_NAMESPACE = os.environ.get("POD_NAMESPACE", "capi-provider-ssh-system")
LEASE_SECONDS = 60


class HostLease:
    """A short, renewed Lease shared by direct and pool mode, across namespaces."""

    def __init__(self, address: str, port: int, machine_uid: str):
        target = f"{address.lower().rstrip('.')}:{port}"
        self.name = "ssh-host-" + hashlib.sha256(target.encode()).hexdigest()[:40]
        self.holder = f"{machine_uid}/{uuid.uuid4()}"
        self.api = kubernetes.client.CoordinationV1Api()

    def _read(self):
        return request(self.api.read_namespaced_lease, self.name, LEASE_NAMESPACE)

    def acquire(self) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        try:
            current = self._read()
        except kubernetes.client.ApiException as exc:
            if exc.status != 404:
                raise
            current = None
        if current:
            spec = current.spec
            renewed = spec.renew_time or spec.acquire_time
            if (
                spec.holder_identity
                and renewed
                and renewed + datetime.timedelta(seconds=spec.lease_duration_seconds or 60) > now
            ):
                return False
        lease = kubernetes.client.V1Lease(
            metadata=kubernetes.client.V1ObjectMeta(
                name=self.name,
                namespace=LEASE_NAMESPACE,
                resource_version=current.metadata.resource_version if current else None,
                labels={"app.kubernetes.io/name": "capi-provider-ssh"},
            ),
            spec=kubernetes.client.V1LeaseSpec(
                holder_identity=self.holder, lease_duration_seconds=LEASE_SECONDS, acquire_time=now, renew_time=now
            ),
        )
        try:
            if current:
                request(self.api.replace_namespaced_lease, self.name, LEASE_NAMESPACE, lease)
            else:
                request(self.api.create_namespaced_lease, LEASE_NAMESPACE, lease)
        except kubernetes.client.ApiException as exc:
            if exc.status == 409:
                return False
            raise
        return True

    def renew(self) -> bool:
        current = self._read()
        if current.spec.holder_identity != self.holder:
            return False
        current.spec.renew_time = datetime.datetime.now(datetime.UTC)
        request(self.api.replace_namespaced_lease, self.name, LEASE_NAMESPACE, current)
        return True

    async def check(self) -> None:
        if not await run_coordination(self.renew):
            raise kopf.TemporaryError("Host operation Lease was lost", delay=15)

    def release(self) -> None:
        current = self._read()
        if current.spec.holder_identity != self.holder:
            return
        current.spec.holder_identity = None
        request(self.api.replace_namespaced_lease, self.name, LEASE_NAMESPACE, current)


@asynccontextmanager
async def host_operation(binding: dict, machine_uid: str):
    lease = HostLease(binding["address"], binding.get("port", 22), machine_uid)
    try:
        acquired = await run_coordination(lease.acquire)
    except Exception as exc:
        raise kopf.TemporaryError("Cannot acquire host operation Lease", delay=15) from exc
    if not acquired:
        raise kopf.TemporaryError("Another operation owns this host", delay=15)
    stopped = asyncio.Event()
    lost = False
    parent = asyncio.current_task()

    async def heartbeat():
        nonlocal lost
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), LEASE_SECONDS / 4)
            except TimeoutError:
                try:
                    if await run_coordination(lease.renew):
                        continue
                except Exception:
                    pass
                lost = True
                parent.cancel()
                return

    renewal = asyncio.create_task(heartbeat())
    try:
        yield lease
    except asyncio.CancelledError as exc:
        if lost:
            raise kopf.TemporaryError("Lost host Lease; interrupted local operation", delay=15) from exc
        raise
    finally:
        stopped.set()
        await renewal
        # Failure to release is safe: only the expiring holder remains recorded.
        with suppress(Exception):
            await run_coordination(lease.release)


def owned_command(
    uid: str, command: str, *, claim: bool = False, cleaned_retry: bool = False, blocking: bool = False
) -> str:
    """Fence even surviving remote commands after a Lease expiry/network partition."""
    if not uid:
        raise kopf.PermanentError("Machine UID is required for remote execution")
    owner = shlex.quote(OWNER_PATH)
    expected = shlex.quote(uid)
    absent = "echo 'No provider ownership record; refusing mutation' >&2; exit 78"
    if claim:
        absent = (
            "if test -e /etc/kubernetes/kubelet.conf || test -e /var/lib/kubelet/config.yaml "
            "|| test -e /etc/kubernetes/manifests/kube-apiserver.yaml || test -d /var/lib/etcd/member "
            "|| test -e /run/cluster-api/bootstrap-success.complete; then "
            "echo 'Existing Kubernetes state has no matching owner' >&2; exit 78; fi; "
            f"install -d -m 0700 /var/lib/capi-provider-ssh; umask 077; printf '%s' {expected} > {owner}.tmp; "
            f"mv {owner}.tmp {owner}"
        )
    elif cleaned_retry:
        absent = (
            "if ! test -e /etc/kubernetes/kubelet.conf && ! test -e /var/lib/kubelet/config.yaml "
            "&& ! test -e /etc/kubernetes/manifests/kube-apiserver.yaml && ! test -d /var/lib/etcd/member "
            "&& ! test -e /run/cluster-api/bootstrap-success.complete; then exit 0; fi; " + absent
        )
    script = (
        f'if test -f {owner}; then test "$(cat {owner})" = {expected} || '
        "{ echo 'Host belongs to another Machine UID' >&2; exit 78; }; "
        f"else {absent}; fi; {command}"
    )
    option = "" if blocking else "-n "
    return f"flock {option}{shlex.quote(REMOTE_LOCK)} sh -ceu {shlex.quote(script)}"


async def durable_bootstrap(conn, uid: str, path: str, command: str, *, timeout: float = 300):
    """Detach bootstrap from the SSH session; persist one result per Machine UID.

    All queued launch attempts acquire the same remote flock and recheck the
    receipt before doing work. A previous started job without a result, after
    acquiring that lock, means an interrupted process: fail closed, never replay.
    """
    from capi_provider_ssh.ssh import SSHResult

    directory = "/var/lib/capi-provider-ssh"
    started = f"{directory}/bootstrap-started"
    receipt = f"{directory}/bootstrap-exit-code"
    output = f"{directory}/bootstrap-output"
    job = (
        f"if test -f {receipt}; then rm -f {shlex.quote(path)}; exit 0; fi; "
        f"if test -f {started}; then "
        f"printf '%s\\n' 'Bootstrap process interrupted; cleanup/replacement required' > {output}; "
        f"printf '123\\n' > {receipt}; rm -f {shlex.quote(path)}; exit 0; fi; "
        f"umask 077; touch {started}; set +e; ({command}) > {output} 2>&1; result=$?; "
        f"printf '%s\\n' \"$result\" > {receipt}.tmp; mv {receipt}.tmp {receipt}"
    )
    launch = "nohup " + owned_command(uid, job, blocking=True) + " </dev/null >/dev/null 2>&1 &"
    submitted = await conn.execute(launch)
    if not submitted.success:
        raise kopf.TemporaryError("Cannot submit the fenced bootstrap job", delay=15)
    observe = (
        f'test "$(cat {shlex.quote(OWNER_PATH)})" = {shlex.quote(uid)} || exit 78; '
        f"if test -f {receipt}; then printf 'CAPI_EXIT='; cat {receipt}; tail -c 8192 {output}; "
        "else printf 'CAPI_PENDING\\n'; fi"
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        result = await conn.execute(observe)
        if not result.success:
            raise kopf.TemporaryError("Cannot observe the UID-owned bootstrap job", delay=15)
        first, _, log = result.stdout.partition("\n")
        if first.startswith("CAPI_EXIT="):
            try:
                code = int(first.removeprefix("CAPI_EXIT="))
            except ValueError as exc:
                raise kopf.TemporaryError("Invalid bootstrap receipt; refusing replay", delay=15) from exc
            return SSHResult(code, log if code == 0 else "", log if code != 0 else "")
        if first != "CAPI_PENDING":
            raise kopf.TemporaryError("Unrecognized bootstrap state; refusing replay", delay=15)
        await asyncio.sleep(2)
    raise kopf.TemporaryError("Bootstrap is still running; observe its receipt on retry", delay=15)
