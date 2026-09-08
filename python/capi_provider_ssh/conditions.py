"""Condition updates which preserve other writers and meaningful transition times."""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable
from copy import deepcopy


def condition(kind: str, status: str, reason: str, message: str) -> dict:
    return {"type": kind, "status": status, "reason": reason, "message": message}


def merge_conditions(existing: Iterable[dict], updates: Iterable[dict], generation: int | None = None) -> list[dict]:
    """Merge by type; a reason/message/generation change is not a status transition."""
    result = {item["type"]: deepcopy(item) for item in existing if item.get("type")}
    for update in updates:
        item = deepcopy(update)
        previous = result.get(item["type"], {})
        if previous.get("status") == item["status"] and previous.get("lastTransitionTime"):
            item["lastTransitionTime"] = previous["lastTransitionTime"]
        else:
            item.setdefault("lastTransitionTime", datetime.datetime.now(datetime.UTC).isoformat())
        if generation is not None:
            item["observedGeneration"] = generation
        result[item["type"]] = item
    return list(result.values())


def patch_conditions(patch, status: dict, meta: dict | None, updates: Iterable[dict]) -> None:
    """Preserve both persisted conditions and earlier updates in this handler patch."""
    existing = {item["type"]: item for item in [*status.get("conditions", []), *patch.status.get("conditions", [])]}
    patch.status["conditions"] = merge_conditions(existing.values(), updates, (meta or {}).get("generation"))


def report_pause(patch, status: dict, meta: dict, check: Callable[[], bool]) -> bool:
    """Report pause without changing Ready or treating an API denial as unpaused."""
    try:
        paused = check()
    except Exception:
        patch_conditions(
            patch,
            status,
            meta,
            [condition("Paused", "Unknown", "PauseCheckFailed", "Cannot establish CAPI pause and owner state")],
        )
        raise
    patch_conditions(
        patch,
        status,
        meta,
        [
            condition(
                "Paused",
                "True" if paused else "False",
                "Paused" if paused else "NotPaused",
                "Reconciliation is paused or awaiting a referenced CAPI owner"
                if paused
                else "Reconciliation is not paused",
            )
        ],
    )
    return paused
