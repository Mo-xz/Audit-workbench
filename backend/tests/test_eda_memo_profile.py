"""Phase 4 of the EDA redesign: the memo reads what the profile computed.

Three things are held here. A result's summary is kept beside its flagged rows,
bounded, with any group too small to report withheld and counted. That summary
reaches the memo writer under its own permission, with recipe frames named by
the tables they were built from. And the memo carries the profile's sections
and an implications list when the writer supplies them, and is unchanged when
it does not.
"""

from __future__ import annotations

import polars as pl
import pytest

from app import analysis_results, workspaces
from app.agent.context.adapters import (
    SUMMARY_AGGREGATES_SOURCE_ID,
    SUMMARY_RESULTS_SOURCE_ID,
    analysis_summary_scope,
)
from app.agent.context.presets import PRESETS
from app.agent.workers import analysis as analysis_worker
from test_workflow_analysis import _payload, _ref_of, _section, _summary_request

BREAKDOWN = {"test": "breakdown", "params": {"dimension": "region", "measure": "amount"}}


@pytest.fixture
def regional():
    ws = workspaces.create_workspace("Regional")
    frame = pl.DataFrame({
        "region": ["North"] * 8 + ["South"] * 5 + ["East"] * 2,
        "amount": [100.0] * 8 + [40.0] * 5 + [999.0, 1.0],
    })
    ws.add_table("sales.csv", frame.write_csv().encode())
    return workspaces.load_workspace(ws.id)


def _save(ws, title: str, spec: dict, **extra) -> dict:
    analysis = ws.add_analysis({"kind": "analytics", "table": "sales", "title": title, "spec": spec, **extra})
    analysis_results.execute_and_record(ws, analysis["id"])
    return analysis


def test_a_small_group_keeps_its_label_and_count_and_loses_its_figures():
    frame = pl.DataFrame({"region": ["North", "East"], "rows": [8, 2], "value": [800.0, 1000.0]})
    aggregate = analysis_results.bounded_aggregate(frame)
    assert aggregate["groups_withheld"] == 1
    assert aggregate["count_column"] == "rows"
    assert aggregate["rows"] == [["North", 8, 800.0], ["East", 2, None]]


def test_a_result_frame_without_counts_must_be_much_smaller_than_its_population():
    """Code that returns the frame it read is rows, whatever its policy says."""
    frame = pl.DataFrame({"region": ["North", "South"], "total": [1.0, 2.0]}).rename({"total": "value"})
    assert analysis_results.bounded_aggregate(frame, population=5) is None
    assert analysis_results.bounded_aggregate(frame, population=100) is not None


def test_the_summary_is_kept_beside_the_result_and_stamped_to_it(regional):
    analysis = _save(regional, "Sales by region", BREAKDOWN)
    fresh = workspaces.load_workspace(regional.id)
    stored = next(item for item in fresh.analyses if item["id"] == analysis["id"])
    aggregate = analysis_results.read_result_aggregate(fresh, stored)
    regions = {row[0]: row for row in aggregate["rows"]}
    assert regions["North"][2] == 800.0
    # East is two rows: its figures would be those rows' amounts.
    assert regions["East"][2] is None and aggregate["groups_withheld"] == 1
    # Nothing was flagged, so there is no flagged-rows evidence to read.
    assert analysis_results.read_exception_evidence(fresh, stored) is None
    # A different result is a different conclusion; its summary is not this one's.
    stale = {**stored, "last_result": {**stored["last_result"], "result_sha1": "other"}}
    assert analysis_results.read_result_aggregate(fresh, stale) is None


def test_the_memo_writer_reads_aggregates_under_their_own_permission(regional):
    _save(regional, "Sales by region", BREAKDOWN)
    scope = analysis_summary_scope(workspaces.load_workspace(regional.id))
    supplied = scope.candidates[SUMMARY_AGGREGATES_SOURCE_ID]
    assert [item.source["test"] for item in supplied] == ["breakdown"]
    assert set(supplied[0].representations) == {"analysis_aggregate"}
    privacy = PRESETS.get("analysis.summary").spec.privacy
    assert privacy.allow_analysis_aggregates
    # Granted to the memo and to the reading that decides what is tested, and
    # to no turn that writes code.
    granted = {preset.preset_id for preset in PRESETS.all() if preset.spec.privacy.allow_analysis_aggregates}
    assert granted == {"analysis.summary", "analysis.reading"}


def test_a_recipe_frame_is_named_by_the_tables_it_was_built_from(workspace_with_data):
    ws = workspace_with_data
    recipe = {
        "version": 1, "name": "profile_party_transactions_1234abcd", "root": "transactions",
        "joins": [{"name": "profile_party_transactions_1234abcd", "left": "transactions", "right": "customers",
                   "how": "left", "left_on": ["cust_id"], "right_on": ["id"]}],
    }
    analysis = ws.add_analysis({
        "kind": "analytics", "table": recipe["name"], "alignment": recipe, "title": "By customer",
        "spec": {"test": "breakdown", "params": {"dimension": "customer", "measure": "amount"}},
    })
    analysis_results.execute_and_record(ws, analysis["id"])
    scope = analysis_summary_scope(workspaces.load_workspace(ws.id))
    projected = next(
        item.source for item in scope.candidates[SUMMARY_RESULTS_SOURCE_ID]
        if item.source["analysis_id"] == analysis["id"]
    )
    assert projected["table"] == "transactions joined to customers"
    assert "profile_party" not in str(projected)


def test_the_memo_carries_profile_sections_and_implications(regional):
    analysis = _save(regional, "Sales by region", BREAKDOWN)
    request = _summary_request(workspaces.load_workspace(regional.id))
    ref = _ref_of(request, analysis["id"])
    accepted = analysis_worker.validate_analysis_summary(
        _payload(
            findings=[{"title": "Nothing failed", "prose": "No exception was found.", "procedures": []}],
            profile=[
                {"section": "People and authority", "prose": "Nobody holds two roles.", "procedures": []},
                {"section": "Where the value is", "prose": f"North holds most of the value ([#{ref}]).",
                 "procedures": [ref]},
            ],
            implications=["Test North individually.", "Drop the regional rotation test."],
        ),
        request,
    )
    markdown = accepted["markdown"]
    headings = [line[3:] for line in markdown.splitlines() if line.startswith("## ")]
    sections = analysis_worker.SUMMARY_SECTIONS
    assert headings == [
        sections[0], "Where the value is", "People and authority",
        sections[1], sections[2], analysis_worker.IMPLICATIONS_SECTION, sections[3],
    ]
    # The cited profile result is placed under its section as a chart.
    assert [(e["analysis"], e["as"]) for e in analysis_worker.parse_embeds(markdown)] == [(analysis["id"], "chart")]
    assert _section(markdown, analysis_worker.IMPLICATIONS_SECTION).strip().splitlines() == [
        "1. Test North individually.", "2. Drop the regional rotation test.",
    ]
    assert analysis["id"] in accepted["cited_analysis_ids"]


def test_a_memo_without_the_new_parts_is_assembled_as_before(regional):
    _save(regional, "Sales by region", BREAKDOWN)
    request = _summary_request(workspaces.load_workspace(regional.id))
    markdown = analysis_worker.validate_analysis_summary(
        _payload(findings=[{"title": "x", "prose": "y", "procedures": []}]), request
    )["markdown"]
    assert [line[3:] for line in markdown.splitlines() if line.startswith("## ")] == list(
        analysis_worker.SUMMARY_SECTIONS
    )


def test_a_profile_section_is_written_once_and_named_from_the_list(regional):
    _save(regional, "Sales by region", BREAKDOWN)
    request = _summary_request(workspaces.load_workspace(regional.id))
    with pytest.raises(Exception, match="written twice|not one of"):
        analysis_worker.validate_analysis_summary(
            _payload(profile=[
                {"section": "Where the value is", "prose": "a", "procedures": []},
                {"section": "Where the value is", "prose": "b", "procedures": []},
            ]),
            request,
        )
    tool = analysis_worker._summary_submission_tool(request)["function"]["parameters"]
    assert tool["properties"]["profile"]["items"]["properties"]["section"]["enum"] == list(
        analysis_worker.PROFILE_SECTIONS
    )
    assert "implications" in tool["required"]


def test_a_repair_keeps_the_profile_and_implications_it_was_not_asked_to_change():
    """Observed live: asked to move one procedure out of the reliance section,
    the rewrite returned without the three profile sections the first draft had,
    and the memo lost the population it described."""
    import json

    earlier = json.dumps({"lead": "a", "profile": [{"section": "Where the value is", "prose": "p", "procedures": []}],
                          "implications": ["Test North."], "reliance": {"prose": "old"}})
    repaired = json.dumps({"lead": "a", "reliance": {"prose": "new"}})
    merged = json.loads(analysis_worker._carry_unrepaired_parts(repaired, earlier))
    assert merged["reliance"] == {"prose": "new"}
    assert merged["profile"][0]["section"] == "Where the value is"
    assert merged["implications"] == ["Test North."]
    kept = json.dumps({"lead": "a", "implications": ["Changed."]})
    assert json.loads(analysis_worker._carry_unrepaired_parts(kept, earlier))["implications"] == ["Changed."]


def _flagging(ws, title: str, code: str) -> dict:
    analysis = ws.add_analysis({"kind": "python", "table": "sales", "title": title,
                                "spec": {"code": code}, "outcome_policy": {"mode": "exception_rows"}})
    analysis_results.execute_and_record(ws, analysis["id"])
    return analysis


def test_a_finding_shows_one_table_and_a_profile_section_three_exhibits(regional):
    """Measured on procurement: 37 exhibits, 24 of them under ten findings."""
    first = _flagging(regional, "Large sales", "result = tables['sales'].filter(pl.col('amount') > 500)")
    second = _flagging(regional, "Tiny sales", "result = tables['sales'].filter(pl.col('amount') < 5)")
    profiles = [_save(regional, f"Breakdown {n}", BREAKDOWN) for n in range(4)]
    request = _summary_request(workspaces.load_workspace(regional.id))
    refs = [_ref_of(request, item["id"]) for item in (first, second, *profiles)]
    markdown = analysis_worker.validate_analysis_summary(
        _payload(
            findings=[{"title": "Outliers", "prose": "Two outlying sales.", "procedures": refs[:2]}],
            profile=[{"section": "Where the value is", "prose": "North holds most.", "procedures": refs[2:]}],
        ),
        request,
    )["markdown"]
    embeds = analysis_worker.parse_embeds(markdown)
    assert [(e["analysis"], e["as"]) for e in embeds if e["as"] == "exception_table"] == [(first["id"], "exception_table")]
    assert [e["analysis"] for e in embeds if e["as"] == "chart"] == [item["id"] for item in profiles[:3]]


def test_an_authored_analysis_with_a_chart_is_drawn(regional):
    analysis = regional.add_analysis({
        "kind": "python", "table": "sales", "title": "Value by region",
        "spec": {"code": "result = tables['sales'].group_by('region').agg(pl.col('amount').sum())"},
        "outcome_policy": {"mode": "informational"}, "viz": {"type": "bar", "x": "region", "y": ["amount"]},
    })
    analysis_results.execute_and_record(regional, analysis["id"])
    request = _summary_request(workspaces.load_workspace(regional.id))
    ref = _ref_of(request, analysis["id"])
    markdown = analysis_worker.validate_analysis_summary(
        _payload(profile=[{"section": "Where the value is", "prose": "By region.", "procedures": [ref]}]),
        request,
    )["markdown"]
    assert [(e["analysis"], e["as"]) for e in analysis_worker.parse_embeds(markdown)] == [(analysis["id"], "chart")]


def test_a_memo_repair_is_sent_the_draft_and_errors_not_the_bundle(regional):
    """The repair that failed at the provider resent 61k tokens and asked for the
    whole memo again; it now sends the reference sheet and asks for changes."""
    import json

    from app.agent.workers.model import WorkerAttempt

    _save(regional, "Sales by region", BREAKDOWN)
    request = _summary_request(workspaces.load_workspace(regional.id))
    draft = json.dumps({"lead": "a", "data_received": "b", "findings": [{"title": "t", "prose": "p", "procedures": []}],
                        "reliance": {"prose": "r"}, "implications": ["i"], "further_work": ["f"]})
    sent = {}

    class Gateway:
        def complete(self, system, user, activity, **kwargs):
            sent.update(kwargs, user=user)
            return {"tool_calls": [{"function": {"name": analysis_worker.SUMMARY_SUBMISSION_TOOL,
                                                 "arguments": json.dumps({"reliance": {"prose": "fixed"}})}}]}

    response = analysis_worker.run_analysis_summary_worker(
        request, Gateway(), WorkerAttempt(2, ("[#1] is argued twice",), draft)
    )
    first = json.loads(sent["conversation"][0]["content"])
    assert "RESOLVED CONTEXT" not in first and "PROCEDURE REFERENCES" in first
    assert sent["tools"][0]["function"]["parameters"]["required"] == []
    merged = json.loads(response)
    # The repair changed one part; every other part is the draft's.
    assert merged["reliance"] == {"prose": "fixed"}
    assert merged["findings"][0]["title"] == "t" and merged["further_work"] == ["f"]


def test_an_uncorrected_memo_records_what_it_was_committed_with(regional):
    _save(regional, "Sales by region", BREAKDOWN)
    request = _summary_request(workspaces.load_workspace(regional.id))
    ref = _ref_of(request, regional.analyses[0]["id"])
    with pytest.raises(analysis_worker.WorkerResponseValidationError) as error:
        analysis_worker.validate_analysis_summary(
            _payload(
                findings=[{"title": "x", "prose": "y", "procedures": [ref]}],
                reliance={"prose": "z", "procedures": [ref]},
            ),
            request,
        )
    assert error.value.partial["unrepaired"] == list(error.value.errors)


def test_the_committed_memo_keeps_the_faults_it_was_committed_with(regional):
    from app.agent.executors import analysis as executors
    from app.agent.executors.model import ExecutorRequest
    from app.workspace_transactions import parent_hashes

    ref = executors.ANALYSIS_SUMMARY_REF
    request = ExecutorRequest(
        executor_id=executors.SUMMARY_EXECUTOR_ID, capability_id="analysis.summarized", unit_id="analysis_summary",
        proposal={"markdown": "Memo.", "cited_analysis_ids": [], "unrepaired": ["[#1] is argued twice"]},
        expected_revision=regional.revision, expected_parents=parent_hashes(regional, [ref]),
    )
    result = executors.execute_analysis_summary(request, executors.AnalysisSummaryExecutorTarget(regional, "run-1"))
    assert list(result.output["unrepaired"]) == ["[#1] is argued twice"]
    assert workspaces.load_workspace(regional.id).analysis_summary["unrepaired"] == ["[#1] is argued twice"]
