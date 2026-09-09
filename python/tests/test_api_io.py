"""Slow/lost API replies must preserve responsiveness, capacity and fencing."""

import asyncio
import contextvars
import threading
from unittest.mock import Mock

import kopf
import kubernetes
import pytest
from urllib3.exceptions import ReadTimeoutError

from capi_provider_ssh import api_io
from capi_provider_ssh.controllers import sshmachine as controller
from tests import test_lifecycle_contract as lifecycle_tests

api = lifecycle_tests.api
ssh = lifecycle_tests.ssh
reconcile = lifecycle_tests.reconcile


@pytest.fixture
def executor():
    pool = api_io.APIExecutor(1, "test-api")
    yield pool
    pool.executor.shutdown(wait=True, cancel_futures=True)


async def wait_event(event):
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("boundary", ["secret", "bootstrap", "reconcile", "delete"])
async def test_slow_api_keeps_heartbeat_and_other_reconcile_responsive(api, ssh, monkeypatch, boundary):
    slow_machine = api.machine("slow")
    other_machine = api.machine("other")
    if boundary == "delete":
        slow_machine = await reconcile(api, slow_machine)
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    reads = []
    method = "read_namespaced_secret" if boundary in {"secret", "bootstrap"} else "get_namespaced_custom_object"
    original = getattr(api, method)

    def delayed(*args, **kwargs):
        if kwargs.get("_request_timeout") and (method == "read_namespaced_secret" or kwargs.get("name") == "slow"):
            reads.append((threading.get_ident(), kwargs.get("_request_timeout")))
            entered.set()
            assert release.wait(2), "API response was not released while the event loop was responsive"
        return original(*args, **kwargs)

    monkeypatch.setattr(api, method, delayed)
    if boundary == "secret":
        work = controller._read_ssh_key("test", "key")
    elif boundary == "bootstrap":
        work = controller._read_bootstrap_data("test", "slow")
    else:
        work = reconcile(api, slow_machine, delete=boundary == "delete")
    task = asyncio.create_task(work)
    try:
        await wait_event(entered)
        ticks = []
        loop = asyncio.get_running_loop()
        loop.call_soon(ticks.append, "heartbeat")
        await asyncio.sleep(0)
        assert ticks == ["heartbeat"]
        if boundary in {"reconcile", "delete"}:
            completed = await asyncio.wait_for(reconcile(api, other_machine), 1)
            assert completed["status"]["ready"] is True
    finally:
        release.set()
        await task
    assert reads
    assert all(thread != main_thread and timeout == api_io.API_TIMEOUT for thread, timeout in reads)


async def test_cancelled_request_holds_lock_and_capacity_until_commit_is_observed(executor):
    entered, release = threading.Event(), threading.Event()
    second = threading.Event()
    events = []
    lock = asyncio.Lock()

    def pending_write():
        entered.set()
        assert release.wait(2)
        events.append("committed")

    async def writer():
        async with lock:
            try:
                await executor.run(pending_write)
                events.append("remote-side-effect")
            finally:
                events.append("lock-release")

    task = asyncio.create_task(writer())
    queued = None
    try:
        await wait_event(entered)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # A second shutdown signal must not release the slot early.
        queued = asyncio.create_task(executor.run(second.set))
        await asyncio.sleep(0.02)
        assert lock.locked()
        assert not task.done()
        assert not second.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        if queued:
            await queued
    assert events == ["committed", "lock-release"]
    assert second.is_set()


async def test_cancelled_queued_work_is_never_submitted(executor):
    entered, release = threading.Event(), threading.Event()
    forbidden = Mock()

    def busy():
        entered.set()
        assert release.wait(2)

    task = asyncio.create_task(executor.run(busy))
    try:
        await wait_event(entered)
        queued = asyncio.create_task(executor.run(forbidden))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
    finally:
        release.set()
        await task
    forbidden.assert_not_called()


async def test_cancelled_request_with_lost_response_preserves_cancellation(executor):
    entered, release = threading.Event(), threading.Event()

    def committed_but_reply_lost():
        entered.set()
        assert release.wait(2)
        raise kopf.TemporaryError("Reply lost after commit", delay=15)

    task = asyncio.create_task(executor.run(committed_but_reply_lost))
    try:
        await wait_event(entered)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await executor.run(lambda: "capacity restored") == "capacity restored"


async def test_coordination_can_run_while_regular_api_pool_is_saturated(monkeypatch, executor):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(api_io, "run_api", executor.run)

    def busy():
        entered.set()
        assert release.wait(2)

    task = asyncio.create_task(api_io.run_api(busy))
    try:
        await wait_event(entered)
        assert await asyncio.wait_for(api_io.run_coordination(lambda: "renewed"), 1) == "renewed"
    finally:
        release.set()
        await task


async def test_executor_preserves_handler_context(executor):
    context = contextvars.ContextVar("handler-identity")
    token = context.set("machine-a")
    try:
        assert await executor.run(context.get) == "machine-a"
    finally:
        context.reset(token)


def test_sdk_requests_have_connect_and_read_timeouts():
    method = Mock(return_value="result")
    assert api_io.request(method, "object", namespace="test") == "result"
    method.assert_called_once_with("object", namespace="test", _request_timeout=api_io.API_TIMEOUT)


def test_transport_failure_is_retryable_without_response_content():
    method = Mock(side_effect=ReadTimeoutError(None, "test", "SYNTHETIC_SECRET"))
    with pytest.raises(kopf.TemporaryError, match="Kubernetes API transport failed") as caught:
        api_io.request(method)
    assert "SYNTHETIC_SECRET" not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("status", [404, 409, 403, 503])
def test_sdk_status_remains_available_for_cas_and_missing_object_handling(status):
    failure = kubernetes.client.ApiException(status=status)
    with pytest.raises(kubernetes.client.ApiException) as caught:
        api_io.request(Mock(side_effect=failure))
    assert caught.value is failure
