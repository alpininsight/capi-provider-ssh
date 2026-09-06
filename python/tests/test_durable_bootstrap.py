"""Remote receipt observation, failure propagation and no speculative replay."""

from unittest.mock import AsyncMock

import kopf
import pytest

from capi_provider_ssh.operations import durable_bootstrap
from capi_provider_ssh.ssh import SSHResult


async def test_pending_job_is_observed_without_resubmission(monkeypatch):
    monkeypatch.setattr("capi_provider_ssh.operations.asyncio.sleep", AsyncMock())
    conn = AsyncMock()
    conn.execute.side_effect = [
        SSHResult(0, "", ""),
        SSHResult(0, "CAPI_PENDING\n", ""),
        SSHResult(0, "CAPI_EXIT=0\nfinished", ""),
    ]
    result = await durable_bootstrap(conn, "uid", "/private/script", "echo example")
    assert result.success and result.stdout == "finished"
    assert sum(c.args[0].startswith("nohup ") for c in conn.execute.call_args_list) == 1


@pytest.mark.parametrize("code", [1, 123, 137])
async def test_remote_failure_is_not_reported_as_success(code):
    conn = AsyncMock()
    conn.execute.side_effect = [SSHResult(0, "", ""), SSHResult(0, f"CAPI_EXIT={code}\nfailed", "")]
    result = await durable_bootstrap(conn, "uid", "/private/script", "echo example")
    assert result.exit_code == code and not result.success and result.stderr == "failed"


@pytest.mark.parametrize("reply", ["CAPI_EXIT=invalid\n", "unexpected\n"])
async def test_unverifiable_receipt_blocks_replay(reply):
    conn = AsyncMock()
    conn.execute.side_effect = [SSHResult(0, "", ""), SSHResult(0, reply, "")]
    with pytest.raises(kopf.TemporaryError, match="refusing replay"):
        await durable_bootstrap(conn, "uid", "/private/script", "echo example")
    assert conn.execute.await_count == 2


async def test_observation_deadline_preserves_the_detached_job():
    conn = AsyncMock()
    conn.execute.return_value = SSHResult(0, "", "")
    with pytest.raises(kopf.TemporaryError, match="observe its receipt"):
        await durable_bootstrap(conn, "uid", "/private/script", "echo example", timeout=0)
    assert conn.execute.await_count == 1
    command = conn.execute.call_args.args[0]
    assert command.startswith("nohup flock ") and "</dev/null >/dev/null 2>&1 &" in command


@pytest.mark.parametrize("stage", ["submission", "observation"])
async def test_failed_remote_transport_does_not_resubmit_bootstrap(stage):
    conn = AsyncMock()
    failure = SSHResult(78, "", "remote ownership or transport failure")
    conn.execute.side_effect = [failure] if stage == "submission" else [SSHResult(0, "", ""), failure]
    with pytest.raises(kopf.TemporaryError, match="Cannot submit|Cannot observe"):
        await durable_bootstrap(conn, "uid", "/private/script", "echo example")
    assert sum(call.args[0].startswith("nohup ") for call in conn.execute.call_args_list) == 1
    assert conn.execute.await_count == (1 if stage == "submission" else 2)
