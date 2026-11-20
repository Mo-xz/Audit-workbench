"""An unreachable provider pauses a run; resuming carries on where it stopped.

The ProcurementAuto full audit lost its route to the provider mid-run. Every
unit after the first then failed in about a second, the stages downstream of
them ran over nothing and reported success, and the run ended
``completed_with_failures`` with no evidence read and no tests written. These
tests hold the replacement: an outage is not a unit failure, it is a pause.
"""

from __future__ import annotations

import http.client
import ssl
import threading
import time
import urllib.error

import pytest

from app import assistant_settings, documents, llm, workspaces
from app.agent import base, runner, store
from app.agent.runtime import Cancelled, DefaultRunRuntime
from conftest import FakeAgentLLM, wait_run


UNREACHABLE = OSError(10065, "A socket operation was attempted to an unreachable host")


# ------------------------------------------------------------ classification
def _transport_failure(monkeypatch, error):
    def fake_urlopen(request, timeout):
        raise error

    assistant_settings.save({"provider": "lmstudio", "model": ""})
    monkeypatch.setattr(llm, "MAX_REQUEST_ATTEMPTS", 1)
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)


def test_a_host_the_network_cannot_reach_is_reported_as_unreachable(monkeypatch):
    _transport_failure(monkeypatch, urllib.error.URLError(UNREACHABLE))

    with pytest.raises(llm.LLMUnreachableError, match="Could not reach"):
        llm.chat([{"role": "user", "content": "hello"}])


def test_a_dropped_connection_is_reported_as_unreachable(monkeypatch):
    _transport_failure(
        monkeypatch, http.client.RemoteDisconnected("closed without response")
    )

    with pytest.raises(llm.LLMUnreachableError):
        llm.chat([{"role": "user", "content": "hello"}])


@pytest.mark.parametrize(
    "error",
    [
        # A read timeout may be this request being too large to answer in time.
        TimeoutError("The read operation timed out"),
        # A refused certificate is configuration; waiting would wait forever.
        urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")),
    ],
    ids=("read-timeout", "certificate"),
)
def test_failures_that_waiting_would_not_fix_stay_ordinary_errors(monkeypatch, error):
    _transport_failure(monkeypatch, error)

    with pytest.raises(llm.LLMError) as raised:
        llm.chat([{"role": "user", "content": "hello"}])
    assert not isinstance(raised.value, llm.LLMUnreachableError)


def test_an_unreachable_provider_is_still_an_llm_error_for_callers_that_cannot_wait():
    assert issubclass(llm.LLMUnreachableError, llm.LLMError)


# ------------------------------------------------------------- gateway pause
def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def _outage_runner(workspace_with_data, monkeypatch, failures):
    """A run whose provider is unreachable for its first ``failures`` calls."""
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        if len(calls) <= failures:
            raise llm.LLMUnreachableError(f"Could not reach the LLM endpoint: {UNREACHABLE}")
        return {"content": "ok"}

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(
        llm,
        "agent_status",
        lambda: {"configured": True, "provider": "outage-test", "model": "model"},
    )
    run = store.new_run(workspace_with_data, "auto")
    run["limits"] = {
        "max_model_turns": 1,
        "max_estimated_prompt_tokens": 100_000,
        "max_completion_tokens": 200_000,
    }
    handle = runner.RunHandle(workspace_with_data.id, run["id"])
    active = base.BaseRunner(workspace_with_data, run, handle)
    active.save()
    return active, handle, calls


def _complete_in_background(active):
    result: dict = {}

    def call():
        try:
            result["answer"] = active.model_gateway.complete(
                "[agent:rcm]\nDraft it", "payload"
            )
        except BaseException as error:  # noqa: BLE001 - asserted by the test
            result["error"] = error

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    return thread, result


def test_an_unreachable_provider_pauses_the_turn_and_resume_sends_it_again(
    workspace_with_data, monkeypatch
):
    active, handle, calls = _outage_runner(workspace_with_data, monkeypatch, failures=1)

    thread, result = _complete_in_background(active)
    _wait_for(lambda: active.run["status"] == "paused")

    durable = store.load_run(workspace_with_data, active.run["id"])
    assert durable["status"] == "paused"
    assert "unreachable host" in durable["provider_outage"]["error"]
    # The request that never got an answer is not charged: the one-turn budget
    # is still there for the retry, which is the call that will be answered.
    assert durable["usage"]["llm_turns"] == 0
    assert any(
        "paused the run" in str(entry.get("content") or entry.get("text") or "")
        for entry in durable.get("narration") or []
    ) or any(
        "paused the run" in str(message.get("content") or "")
        for message in durable.get("messages") or []
    )
    assert thread.is_alive(), "the turn waits; it does not fail"

    handle.resume.set()
    thread.join(timeout=5)

    assert result == {"answer": "ok"}
    assert len(calls) == 2
    durable = store.load_run(workspace_with_data, active.run["id"])
    assert durable["status"] == "executing"
    assert "provider_outage" not in durable
    assert len(durable["provider_outages"]) == 1
    assert durable["usage"]["llm_turns"] == 1
    events = [event["type"] for event in store.read_events(workspace_with_data, active.run["id"])]
    assert "provider_unreachable" in events
    assert "provider_resumed" in events


def test_a_still_dead_connection_pauses_again_after_resume(
    workspace_with_data, monkeypatch
):
    active, handle, calls = _outage_runner(workspace_with_data, monkeypatch, failures=2)

    thread, result = _complete_in_background(active)
    _wait_for(lambda: active.run["status"] == "paused")
    handle.resume.set()
    _wait_for(lambda: len(calls) == 2 and active.run["status"] == "paused")
    assert thread.is_alive()

    handle.resume.set()
    thread.join(timeout=5)
    assert result == {"answer": "ok"}
    assert len(active.run["provider_outages"]) == 2


def test_stopping_a_paused_run_cancels_the_waiting_turn(workspace_with_data, monkeypatch):
    active, handle, calls = _outage_runner(workspace_with_data, monkeypatch, failures=5)

    thread, result = _complete_in_background(active)
    _wait_for(lambda: active.run["status"] == "paused")
    handle.cancel.set()
    handle.resume.set()  # what ``runner.cancel_run`` does to wake any wait
    thread.join(timeout=5)

    assert isinstance(result.get("error"), Cancelled)
    assert len(calls) == 1


# -------------------------------------------------------------- runtime wait
def _runtime(workspace_with_data):
    run = store.new_run(workspace_with_data, "auto")
    handle = runner.RunHandle(workspace_with_data.id, run["id"])
    runtime = DefaultRunRuntime(
        workspace=workspace_with_data,
        run=run,
        state_lock=threading.RLock(),
        handle=handle,
    )
    runtime.set_status("executing")
    return runtime, handle


def test_parallel_units_share_one_pause_and_one_resume(workspace_with_data):
    runtime, handle = _runtime(workspace_with_data)
    paused_notes = []
    returned = []

    def unit():
        runtime.wait_for_provider(
            llm.LLMUnreachableError("down"), on_pause=paused_notes.append
        )
        returned.append(True)

    threads = [threading.Thread(target=unit, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    _wait_for(lambda: runtime.run["status"] == "paused")
    time.sleep(0.3)  # every unit is now waiting on the one pause

    handle.resume.set()
    for thread in threads:
        thread.join(timeout=5)

    assert len(returned) == 4, "one resume releases every waiting unit"
    assert len(paused_notes) == 1, "the pause is said once, not per unit"
    assert runtime.run["status"] == "executing"
    assert len(runtime.run["provider_outages"]) == 1
    assert not handle.resume.is_set()


def test_a_call_that_failed_before_the_last_resume_retries_without_pausing(
    workspace_with_data,
):
    runtime, handle = _runtime(workspace_with_data)
    started_before_resume = time.monotonic()

    waiter = threading.Thread(
        target=runtime.wait_for_provider,
        args=(llm.LLMUnreachableError("down"),),
        daemon=True,
    )
    waiter.start()
    _wait_for(lambda: runtime.run["status"] == "paused")
    handle.resume.set()
    waiter.join(timeout=5)

    # A sibling whose call was already in flight against the same outage
    # comes back after the resume. It is answered by that resume.
    runtime.wait_for_provider(
        llm.LLMUnreachableError("down"), call_started=started_before_resume
    )
    assert runtime.run["status"] == "executing"
    assert len(runtime.run["provider_outages"]) == 1


def test_a_runtime_with_no_one_to_resume_it_raises(workspace_with_data):
    run = store.new_run(workspace_with_data, "auto")
    runtime = DefaultRunRuntime(
        workspace=workspace_with_data, run=run, state_lock=threading.RLock()
    )
    error = llm.LLMUnreachableError("down")

    with pytest.raises(llm.LLMUnreachableError):
        runtime.wait_for_provider(error)


# ------------------------------------------------------------- workflow run
POLICY_TEXT = b"Treasury Manual\n\nPayments above the limit need two approvers."
EVIDENCE_TEXT = b"Payment Instruction 0041\n\nPay vendor 12,400.00 on 3 May."


def test_a_workflow_run_pauses_through_an_outage_and_completes_on_resume(monkeypatch):
    """The incident, end to end: the stage is neither failed nor skipped past."""

    # A provider that needs no key, so the run reaches the (patched) chat call
    # in a checkout with no dotenv.
    assistant_settings.save({"provider": "lmstudio", "model": ""})
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    ws = workspaces.create_workspace("Outage engagement")
    policy = documents.add_document(ws, "manual.txt", POLICY_TEXT)
    voucher = documents.add_document(ws, "scan.txt", EVIDENCE_TEXT)
    outage = threading.Event()
    outage.set()

    def category(user_view):
        value = "evidence" if "Payment Instruction" in user_view else "policy"
        return {"category": value, "confidence": "high", "rationale": "Opening page."}

    fake = FakeAgentLLM({"agent:document_category": category})

    def chat(messages, **kwargs):
        if outage.is_set():
            raise llm.LLMUnreachableError(f"Could not reach the LLM endpoint: {UNREACHABLE}")
        return fake(messages, **kwargs)

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(
        llm,
        "agent_status",
        lambda: {"configured": True, "backend": "fake", "model": "fake"},
    )

    run = runner.start_command_run(
        ws, "auto",
        {
            "source": "tab_button",
            "text": "Categorize the documents.",
            "goal_template": "document_analysis",
            "requested_outcomes": ["documents.categorized"],
            "target_refs": [f"document:{policy['id']}", f"document:{voucher['id']}"],
        },
        context={"document_ids": [policy["id"], voucher["id"]]},
    )
    paused = wait_run(ws, run["id"], statuses=("paused",), timeout=30)
    units = [
        unit
        for stage in paused["workflow"]["stages"]
        for unit in stage.get("units") or []
    ]
    assert units, "the stage expanded its units before the outage"
    assert not [unit for unit in units if unit["status"] == "failed"]
    assert runner.get_handle(run["id"]) is not None, "the worker is waiting, not gone"

    outage.clear()
    runner.resume_run(ws, run["id"])
    done = wait_run(ws, run["id"], timeout=60)

    assert done["status"] == "completed", done.get("error")
    assert done["provider_outages"]
    assert not done.get("error")
    ws = workspaces.load_workspace(ws.id)
    categories = {item["id"]: item.get("category") for item in ws.documents}
    assert categories == {policy["id"]: "policy", voucher["id"]: "evidence"}
