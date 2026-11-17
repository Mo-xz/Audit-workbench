"""Answer model calls from recordings instead of a provider.

A demonstration on a machine with no route to a model provider can still show
a step the model performs, provided that step was performed once before with
one. Every call :func:`llm.chat` makes is already recorded whole in the
workspace's telemetry database — the request it sent and the message it got
back — so with ``LLM_REPLAY=on`` the transport looks the request up there and
returns the recorded message without opening a connection.

Only answers the run *kept* are ever served:

- A call that failed at the transport never completed, and is not a recording.
- A completed call whose answer was empty, or cut off at the output limit, was
  retried with the same request; the retry is the recording.
- A completed call whose answer a validator rejected was followed by a repair
  turn: the same request with "…could not be used: <reason>" appended to its
  last message. The original request is answered with the *last* answer of
  that chain, so a replayed unit passes validation on its first turn and the
  rejected draft is never shown, never revalidated, never repaired again.

Two matches, tried in order:

1. ``exact`` — a recorded call whose request bytes hash to the same sha256.
   The same workspace state, code and settings ask the same question.
2. ``same_step`` — the calls recorded for the same stage over the same
   artifact refs, from the most recent run that made them, served in their
   recorded order across the successive calls of one run. This survives a
   prompt that moved by a byte; the answer still has to pass today's
   validators, or the unit fails exactly as it would have live. A call with no
   artifact refs has no step identity, and only an exact match answers it.

Nothing else answers. A request neither match covers fails with a plain
error: replay repeats what was recorded, it never reaches the network and
never improvises. Where one request was recorded more than once, the newest
recording wins, so performing a step again with a live model is how a
recording is replaced. Replayed calls are recorded too, marked with the call
they were answered from, so the debug console shows what was replayed; they
are never matched themselves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
import threading

from . import debug_store

ENV_VAR = "LLM_REPLAY"
_ON = {"1", "on", "true", "yes"}
#: How every repair turn in the codebase tells the model its answer was
#: rejected; the suffix a repair request adds to the request it repairs.
REPAIR_MARKER = "could not be used"

_counters: dict[tuple, int] = {}
_counters_lock = threading.Lock()


def enabled() -> bool:
    """True when model calls are answered from recordings, read per call."""
    return str(os.environ.get(ENV_VAR) or "").strip().lower() in _ON


@dataclass(frozen=True)
class Recording:
    call_id: str
    match: str
    message: dict
    payload: dict | None
    #: The calls whose answers were rejected on the way to this one, if any.
    superseded: tuple[str, ...] = ()


def request_sha256(body: Mapping) -> str:
    """The hash the live transport records for the bytes it sends."""
    return hashlib.sha256(json.dumps(body).encode("utf-8")).hexdigest()


def _refs(context: Mapping) -> tuple[str, ...]:
    return tuple(sorted(str(item) for item in context.get("artifact_refs") or []))


def _usable(record: Mapping) -> bool:
    """An answer the transport would have handed on: not empty, not cut off."""
    message = record.get("normalized_message")
    if not isinstance(message, dict):
        return False
    if str(record.get("finish_reason") or "") == "length":
        return False
    return bool(str(message.get("content") or "").strip() or message.get("tool_calls"))


def _repairs(earlier: Mapping, later: Mapping) -> bool:
    """True when ``later`` is a repair turn for ``earlier``'s request.

    The same messages, except that the last one carries the original text with
    a rejection appended. Every repair path builds its turn from the original
    request rather than from the previous repair, so a chain of repairs all
    extend the first request.
    """
    first = (earlier.get("request") or {}).get("messages") or []
    second = (later.get("request") or {}).get("messages") or []
    if not first or len(first) != len(second) or first[:-1] != second[:-1]:
        return False
    head, tail = first[-1], second[-1]
    if head.get("role") != tail.get("role"):
        return False
    original, repaired = head.get("content"), tail.get("content")
    if not isinstance(original, str) or not isinstance(repaired, str):
        return False
    return (
        len(repaired) > len(original)
        and repaired.startswith(original)
        and REPAIR_MARKER in repaired[len(original):]
    )


def _load(handle, call_id: str) -> dict | None:
    row = handle.execute("SELECT record FROM llm_calls WHERE id = ?", (call_id,)).fetchone()
    return json.loads(row["record"]) if row is not None else None


def _run_calls(handle, run_id: str, stage: str) -> list[dict]:
    """A recorded run's completed calls for one stage, oldest first."""
    rows = handle.execute(
        "SELECT record FROM llm_calls"
        " WHERE status = 'completed' AND run_id = ? AND stage = ?"
        " AND json_extract(record, '$.replay') IS NULL"
        " ORDER BY started_at",
        (run_id, stage),
    ).fetchall()
    return [json.loads(row["record"]) for row in rows]


def _kept(handle, record: dict) -> tuple[dict, tuple[str, ...]]:
    """The answer the run finally kept for this call's request.

    The call itself, unless a later call in the same run repaired it — then
    the last usable repair, with the ids of the answers it replaced.
    """
    correlation = record.get("correlation") or {}
    run_id = str(correlation.get("run_id") or "")
    stage = str(correlation.get("stage") or "")
    if not run_id or not stage:
        return record, ()
    started = str(record.get("started_at") or "")
    chain = [
        item
        for item in _run_calls(handle, run_id, stage)
        if str(item.get("started_at") or "") > started and _repairs(record, item)
    ]
    usable = [item for item in chain if _usable(item)]
    if not usable:
        return record, ()
    final = usable[-1]
    replaced = tuple(
        str(item["id"]) for item in [record, *chain] if item["id"] != final["id"]
    )
    return final, replaced


def _recording(handle, record: dict, match: str) -> Recording:
    final, replaced = _kept(handle, record)
    payload = final.get("raw_response")
    return Recording(
        call_id=str(final["id"]),
        match=match,
        message=dict(final["normalized_message"]),
        payload=dict(payload) if isinstance(payload, dict) else None,
        superseded=replaced,
    )


def _same_request(first: Mapping, second: Mapping) -> bool:
    return (first.get("request") or {}) == (second.get("request") or {})


def _exact(handle, body: Mapping) -> Recording | None:
    rows = handle.execute(
        "SELECT id FROM llm_calls"
        " WHERE status = 'completed'"
        " AND json_extract(record, '$.request_sha256') = ?"
        " AND json_extract(record, '$.replay') IS NULL"
        " ORDER BY started_at DESC",
        (request_sha256(body),),
    ).fetchall()
    for row in rows:
        record = _load(handle, row["id"])
        if record is not None and _usable(record):
            return _recording(handle, record, "exact")
    return None


def _same_step(handle, context: Mapping, workspace_id: str) -> Recording | None:
    stage = str(context.get("stage") or "")
    refs = _refs(context)
    if not stage or not refs:
        return None
    rows = handle.execute(
        "SELECT id, run_id, correlation FROM llm_calls"
        " WHERE status = 'completed' AND stage = ?"
        " AND json_extract(record, '$.replay') IS NULL"
        " ORDER BY started_at",
        (stage,),
    ).fetchall()
    matching = [
        (str(row["run_id"] or ""), str(row["id"]))
        for row in rows
        if _refs(json.loads(row["correlation"] or "{}")) == refs
    ]
    if not matching:
        return None
    latest_run = matching[-1][0]
    records = [
        record
        for run_id, call_id in matching
        if run_id == latest_run and (record := _load(handle, call_id)) is not None
    ]
    # One entry per question the run asked. A repair, or a retry of an empty
    # or cut-off answer, is the same question asked again, not a new one.
    questions = [
        record
        for index, record in enumerate(records)
        if not any(
            _repairs(earlier, record) or _same_request(earlier, record)
            for earlier in records[:index]
        )
    ]
    owner = str(context.get("run_id") or context.get("chat_id") or "")
    key = (workspace_id, owner, stage, refs)
    with _counters_lock:
        position = _counters.get(key, 0)
        _counters[key] = position + 1
    question = questions[min(position, len(questions) - 1)]
    answer = next(
        (
            record
            for record in reversed(records)
            if _same_request(record, question) and _usable(record)
        ),
        None,
    )
    return _recording(handle, answer, "same_step") if answer is not None else None


def find(body: Mapping, context: Mapping) -> Recording | None:
    """The answer kept for this request in the calling workspace, or None."""
    workspace_id = str(context.get("workspace_id") or "")
    if not workspace_id:
        return None
    handle = debug_store.connection(workspace_id)
    return _exact(handle, body) or _same_step(handle, context, workspace_id)


def _reset_for_tests() -> None:
    with _counters_lock:
        _counters.clear()


__all__ = ["ENV_VAR", "REPAIR_MARKER", "Recording", "enabled", "find", "request_sha256"]
