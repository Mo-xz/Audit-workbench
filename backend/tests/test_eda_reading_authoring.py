"""Phase 4 of the EDA redesign: one reading decides, one turn writes.

The reading may now say what kind of data this is (``characterize``) and ask
questions of the population (``explore``) beside its assertions. Those
judgements are kept beside the data they read and reach the memo; the work
items reach a single authoring turn that answers every one, once, as code.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from app import analysis_results, workspaces
from app.agent import register
from app.agent.capabilities import ANALYSIS_REGISTRY
from app.agent.context import ContextResolver, analysis_authoring_scope
from app.agent.context.adapters import SUMMARY_READING_SOURCE_ID, analysis_summary_scope
from app.agent.workers import analysis as analysis_worker
from app.agent.workers.model import WorkerRequest, WorkerResponseValidationError
from test_analysis_reading_worker import _empty, reading_request, validate  # noqa: F401
from test_workflow_analysis import (
    _analysis_run,
    _drive,
    _fake_model,
    _payload,
    _reading_adding,
    _section,
    _stage,
    _summary_request,
)


# ------------------------------------------------------------------ reading
def test_characterize_and_explore_survive_the_reading_validator(validate):
    accepted = validate({
        **_empty(),
        "characterize": [{"fact": "Every order total is 9.", "implication": "A total test cannot fail."}],
        "explore": [{"frame": "invoices", "columns": ["amount"], "question": "How are amounts spread?",
                     "why": "Where the value is."}],
    })
    assert accepted["characterize"] == [
        {"fact": "Every order total is 9.", "implication": "A total test cannot fail."}
    ]
    assert [item["question"] for item in accepted["explore"]] == ["How are amounts spread?"]


def test_an_explore_question_becomes_an_explore_work_item():
    settled = register.merge((), {
        "add": [{"frame": "invoices", "columns": ["amount"], "assertion": "No amount is negative.",
                 "why": "Credits are posted elsewhere."}],
        "explore": [{"frame": "invoices", "columns": ["amount"], "question": "How are amounts spread?",
                     "why": "Where the value is."}],
        "characterize": [{"fact": "Totals never vary.", "implication": "Nothing to compare."}],
    })
    kinds = {item.ref: item.kind for item in settled.authored}
    assert kinds == {"R01": "assert", "E01": "explore"}
    assert [c.fact for c in settled.characterized] == ["Totals never vary."]
    # And the payload a run keeps carries both back.
    restored = register.from_payload(settled.payload())
    assert {item.kind for item in restored.authored} == {"assert", "explore"}
    assert restored.characterized == settled.characterized


# ------------------------------------------------------------ reading store
@pytest.fixture
def sales():
    ws = workspaces.create_workspace("Reading store")
    ws.add_table("sales.csv", pl.DataFrame({"region": ["N", "S"], "amount": [1.0, 2.0]}).write_csv().encode())
    # The memo needs one recorded procedure to write over.
    analysis = ws.add_analysis({"kind": "analytics", "table": "sales", "title": "Sales by region",
                                "spec": {"test": "breakdown", "params": {"dimension": "region", "measure": "amount"}}})
    analysis_results.execute_and_record(ws, analysis["id"])
    return workspaces.load_workspace(ws.id)


def _judged() -> register.Register:
    return register.merge((), {
        "characterize": [{"fact": "Every sale is one unit.", "implication": "Quantity tests cannot fail."}],
        "unanswerable": [{"question": "Who approved each sale?", "why": "No approver column exists."}],
    })


def test_the_reading_is_kept_while_its_data_is_unchanged(sales):
    register.save_reading(sales, _judged())
    kept = register.load_reading(workspaces.load_workspace(sales.id))
    assert kept == {
        "characterized": [{"fact": "Every sale is one unit.", "implication": "Quantity tests cannot fail."}],
        "unanswerable": [{"question": "Who approved each sale?", "why": "No approver column exists."}],
    }
    sales.replace_table("sales", "sales.csv", pl.DataFrame(
        {"region": ["N", "S", "E"], "amount": [1.0, 2.0, 3.0]}).write_csv().encode())
    # A judgement about other data is no judgement about this data.
    assert register.load_reading(workspaces.load_workspace(sales.id)) is None


def test_a_reading_with_nothing_to_say_is_not_kept_as_one(sales):
    register.save_reading(sales, register.merge((), {}))
    assert register.load_reading(workspaces.load_workspace(sales.id)) is None


# ---------------------------------------------------------------- the memo
def test_the_memo_places_what_the_data_cannot_answer(sales):
    register.save_reading(sales, _judged())
    fresh = workspaces.load_workspace(sales.id)
    supplied = analysis_summary_scope(fresh).candidates[SUMMARY_READING_SOURCE_ID]
    assert [item.source["unanswerable"][0]["question"] for item in supplied] == ["Who approved each sale?"]

    request = _summary_request(fresh)
    assert analysis_worker._summary_reading(request)["characterized"][0]["fact"] == "Every sale is one unit."
    markdown = analysis_worker.validate_analysis_summary(
        _payload(findings=[{"title": "x", "prose": "y", "procedures": []}],
                 implications=["Drop the quantity test."]),
        request,
    )["markdown"]
    headings = [line[3:] for line in markdown.splitlines() if line.startswith("## ")]
    assert headings[-3:] == [
        analysis_worker.IMPLICATIONS_SECTION,
        analysis_worker.UNANSWERABLE_SECTION,
        analysis_worker.SUMMARY_SECTIONS[3],
    ]
    assert "**Who approved each sale?** No approver column exists." in _section(
        markdown, analysis_worker.UNANSWERABLE_SECTION
    )


def test_the_writer_is_handed_the_reading_once(sales, monkeypatch):
    register.save_reading(sales, _judged())
    request = _summary_request(workspaces.load_workspace(sales.id))
    sent = {}

    class Gateway:
        def complete(self, system, user, activity, **kwargs):
            sent["user"] = user
            raise RuntimeError("stop")

    from app.agent.workers.model import WorkerAttempt

    with pytest.raises(RuntimeError):
        analysis_worker.run_analysis_summary_worker(request, Gateway(), WorkerAttempt(1))
    payload = json.loads(sent["user"])
    assert payload["WHAT THE READING ESTABLISHED"]["characterized"][0]["fact"] == "Every sale is one unit."
    # Promoted, not also left in the bundle the writer reads.
    assert "Every sale is one unit." not in json.dumps(payload["RESOLVED CONTEXT"])


# --------------------------------------------------------------- authoring
def _authoring_request(ws, items) -> WorkerRequest:
    capability = ANALYSIS_REGISTRY.get("analysis.definitions_ready")
    _manifest, bundle = ContextResolver().resolve(
        ws, capability, {"id": "analysis_authoring"}, analysis_authoring_scope(ws, items)
    )
    return WorkerRequest(
        worker_id="analysis.definitions", capability_id=capability.id,
        unit_id="analysis_authoring", context=bundle,
    )


ITEMS = [
    {"ref": "R01", "kind": "assert", "frame": "sales", "columns": ["amount"],
     "statement": "No sale is negative.", "why": "Credits post elsewhere."},
    {"ref": "E01", "kind": "explore", "frame": "sales", "columns": ["region", "amount"],
     "statement": "Where is the value?", "why": "Concentration."},
]


def _answer(ref, code, policy, **extra):
    return {"ref": ref, "frame": "sales", "title": f"{ref} title", "note": "n",
            "code": code, "outcome_policy": policy, **extra}


def test_every_item_is_answered_and_explore_is_charted(sales):
    request = _authoring_request(sales, ITEMS)
    accepted = analysis_worker.validate_authoring_proposal({
        "analyses": [
            _answer("R01", "result = tables['sales'].filter(pl.col('amount') < 0)", "exception_rows"),
            _answer("E01", "result = tables['sales'].group_by('region').agg(pl.col('amount').sum())",
                    "informational", chart={"type": "bar", "x": "region", "y": ["amount"]}),
        ],
        "declined": [],
    }, request)
    by_ref = {item["ref"]: item for item in accepted["analyses"]}
    assert by_ref["R01"]["outcome_policy"] == {"mode": "exception_rows"}
    assert by_ref["E01"]["outcome_policy"] == {"mode": "informational"}
    assert by_ref["E01"]["viz"] == {"type": "bar", "x": "region", "y": ["amount"]}


def test_an_explore_answer_is_never_a_list_of_exceptions(sales):
    request = _authoring_request(sales, ITEMS)
    with pytest.raises(WorkerResponseValidationError, match="informational"):
        analysis_worker.validate_authoring_proposal({
            "analyses": [
                _answer("R01", "result = tables['sales'].filter(pl.col('amount') < 0)", "exception_rows"),
                _answer("E01", "result = tables['sales']", "exception_rows"),
            ],
            "declined": [],
        }, request)


def test_an_unanswered_item_is_repaired_and_a_wholly_declined_set_is_an_answer(sales):
    request = _authoring_request(sales, ITEMS)
    with pytest.raises(WorkerResponseValidationError, match="E01 has no answer"):
        analysis_worker.validate_authoring_proposal({
            "analyses": [_answer("R01", "result = tables['sales'].filter(pl.col('amount') < 0)",
                                 "exception_rows")],
            "declined": [],
        }, request)
    with pytest.raises(WorkerResponseValidationError, match=analysis_worker.NOTHING_NEW_TO_ANALYSE):
        analysis_worker.validate_authoring_proposal({
            "analyses": [],
            "declined": [{"ref": "R01", "reason": "No sign convention."},
                         {"ref": "E01", "reason": "One region only."}],
        }, request)


def test_an_explore_item_is_saved_as_an_informational_analysis(workspace_with_data, monkeypatch):
    """End to end through the batched binder: one turn, both kinds."""
    ws = workspace_with_data

    def reading(user):
        answer = _reading_adding("transactions", ["invoice_no"])(user)
        answer["explore"] = [{"frame": "transactions", "columns": ["cust_id"],
                              "question": "How is activity spread across customers?", "why": "Concentration."}]
        return answer

    fake = _fake_model(monkeypatch)
    fake.overrides["agent:analysis_reading"] = reading
    run = _analysis_run(ws, command={"source": "chat", "text": "Analyse the tables",
                                     "target_refs": ["table:transactions"]})
    _drive(ws, run, "analysis.definitions_ready")

    units = _stage(run, "analysis.definitions_ready")["units"]
    assert [unit["status"] for unit in units] == ["succeeded"]
    assert [c["tag"] for c in fake.calls].count("agent:analysis_definitions") == 1
    saved = {item["title"]: item for item in workspaces.load_workspace(ws.id).analyses}
    assert saved["E01 on transactions"]["outcome_policy"] == {"mode": "informational"}
    assert saved["R01 on transactions"]["outcome_policy"] == {"mode": "exception_rows"}
