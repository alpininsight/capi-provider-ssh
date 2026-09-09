"""Bounded, cancellation-safe execution of synchronous Kubernetes client I/O."""

from __future__ import annotations

import asyncio
import contextvars
import functools
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakKeyDictionary

import kopf
from urllib3.exceptions import HTTPError

API_TIMEOUT = (5, 10)
API_WORKERS = 8


def request(method, *args, **kwargs):
    """Bound each SDK request; never expose transport response bodies in status."""
    kwargs["_request_timeout"] = API_TIMEOUT
    try:
        return method(*args, **kwargs)
    except (HTTPError, OSError):
        pass
    # Raise outside the except block: tracebacks must not retain response data.
    raise kopf.TemporaryError("Kubernetes API transport failed; retrying reconciliation", delay=15)


class APIExecutor:
    """Keep capacity and caller locks until an in-flight SDK operation finishes.

    Cancelling an asyncio future cannot stop its thread. Releasing a Machine
    lock or a concurrency slot early would let old writes race a new reconcile.
    Waiting callers remain cancellable; submitted work is drained before
    cancellation propagates. SDK request timeouts bound blocked network I/O.
    """

    def __init__(self, workers: int, name: str):
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self.slots = WeakKeyDictionary()

    async def run(self, function, *args, **kwargs):
        loop = asyncio.get_running_loop()
        slots = self.slots.setdefault(loop, asyncio.Semaphore(self.workers))
        async with slots:
            context = contextvars.copy_context()
            future = loop.run_in_executor(self.executor, context.run, functools.partial(function, *args, **kwargs))
            cancelled = None
            while True:
                try:
                    result = await asyncio.shield(future)
                except asyncio.CancelledError as exc:
                    if future.done():
                        raise
                    cancelled = exc
                    continue
                except Exception:
                    if cancelled is not None:
                        raise cancelled from None
                    raise
                if cancelled is not None:
                    raise cancelled
                return result


_api = APIExecutor(API_WORKERS, "provider-api")
# Renewals must not queue behind slow inventory/Secret requests.
_coordination = APIExecutor(2, "provider-lease")
run_api = _api.run
run_coordination = _coordination.run
