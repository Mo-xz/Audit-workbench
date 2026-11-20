"""Auto mode confirms the findings its report carries; permission mode cannot.

The report takes only confirmed findings, and confirmation was an auditor's act
that no stage performed. A Full audit in auto mode therefore drafted every
finding and then wrote a report stating that none had been identified. The
report stage now confirms, on the run's authority and immediately before it
assembles the draft, the findings that pass the checks an auditor's own
confirmation must pass — and the record says the agent confirmed them.
"""

from __future__ import annotations

import pytest

from app import engagement_record, findings, report, workspaces
from app.agent import audit_execution, runner, store
from app.agent import capabilities as audit_capabilities
from app.agent.capabilities import reporting as reporting_capabilities
from app.agent.routing import resolve_route
from test_report import complete_finding_payload, linked_workspace


@pytest.fixture
def engagement(workspace_with_data):
    """A workspace holding one supported finding nobody has confirmed, and the
    empty-of-findings report an earlier run wrote over it."""

    ws, rcm, procedure, execution, _analysis, anchor = linked_workspace(workspace_with_data)
    item = findings.add(
        ws,
        {**complete_finding_payload(rcm, procedure, execution, anchor), "auditor_confirmed": False},
    )
    report.generate(ws, use_model=False)
    ws = workspaces.load_workspace(ws.id)
    assert "No auditor-confirmed" in report.hydrate(ws)["markdown"]
    return ws, item, (rcm, procedure, execution, anchor)


def _report_ready(ws, scope: dict):
    return audit_capabilities.REGISTRY.get("report.working_draft").readiness(ws, scope)


def _run_report(ws, mode: str, monkeypatch):
    """Run the report binding the way the scheduler would, without a model."""

    real = audit_execution.generate_report_draft
    monkeypatch.setattr(
        audit_execution,
        "generate_report_draft",
        lambda workspace, **kwargs: real(workspace, **{**kwargs, "model": None}),
    )
    run = store.new_command_run(
        ws,
        mode,
        {
            "source": "follow_up",
            "text": "Write the report",
            "requested_outcomes": ["report.working_draft"],
        },
    )
    assert resolve_route(ws, run) == "workflow"
    run = store.load_run(ws, run["id"])
    command = audit_execution.AuditWorkflowExecution(
        ws, run, runner.RunHandle(ws.id, run["id"])
    )
    capability = audit_capabilities.REGISTRY.get("report.working_draft")
    result = command._bind_report(
        workspaces.load_workspace(ws.id), command.run, capability, {}, {"id": "report"}
    )
    return command, result


def test_an_existing_report_is_redone_in_auto_mode_while_findings_await_confirmation(
    engagement,
):
    """Without this, the empty report of an earlier run is reused for ever."""

    ws, _item, _links = engagement

    auto = _report_ready(ws, {"permission_mode": False})
    assert auto.state == "missing"
    assert auto.details["confirmable"] == 1
    # Outside a run, and in permission mode, nobody may confirm: the report is
    # what it is.
    assert _report_ready(ws, {}).state == "satisfied"
    assert _report_ready(ws, {"permission_mode": True}).state == "satisfied"


def test_an_auto_run_confirms_the_finding_and_the_report_carries_it(engagement, monkeypatch):
    ws, item, _links = engagement

    command, result = _run_report(ws, "auto", monkeypatch)

    assert result.status == "succeeded"
    reloaded = workspaces.load_workspace(ws.id)
    (stored,) = reloaded.findings
    assert stored["auditor_confirmed"] is True
    assert stored["confirmed_by_kind"] == "agent"
    assert stored["confirmed_by"] == reporting_capabilities.AGENT_CONFIRMER
    # Confirming is not authoring: the record still says who wrote it.
    assert stored["created_by"] == item["created_by"]
    markdown = report.hydrate(reloaded)["markdown"]
    assert item["title"] in markdown
    assert "**Confirmation:** confirmed by an auto-mode run" in markdown
    assert command.run["usage"]["llm_turns"] == 0
    # Nothing left to confirm, so the report is not redone again.
    assert _report_ready(reloaded, {"permission_mode": False}).state == "satisfied"


def test_a_permission_run_leaves_confirmation_to_the_auditor(engagement, monkeypatch):
    ws, _item, _links = engagement

    _run_report(ws, "permission", monkeypatch)

    (stored,) = workspaces.load_workspace(ws.id).findings
    assert stored["auditor_confirmed"] is False
    assert "confirmed_by_kind" not in stored


def test_a_finding_failing_support_is_left_out_and_named_on_the_run(engagement, monkeypatch):
    ws, _item, (rcm, procedure, execution, anchor) = engagement
    incomplete = findings.add(
        ws,
        {
            **complete_finding_payload(rcm, procedure, execution, anchor),
            "title": "A finding whose narrative is unfinished",
            "narrative": "## Condition\n\nSomething happened.\n",
            "auditor_confirmed": False,
        },
    )

    command, _result = _run_report(workspaces.load_workspace(ws.id), "auto", monkeypatch)

    by_id = {row["id"]: row for row in workspaces.load_workspace(ws.id).findings}
    assert by_id[incomplete["id"]]["auditor_confirmed"] is False
    warnings = command.run.get("warnings") or []
    assert any(
        incomplete["title"] in text and "not confirmed in auto mode" in text
        for text in warnings
    )


def test_the_auditor_confirming_replaces_the_runs_confirmation(engagement, monkeypatch):
    ws, item, _links = engagement
    _run_report(ws, "auto", monkeypatch)
    ws = workspaces.load_workspace(ws.id)

    record = engagement_record
    assert any(
        point["key"] == "run_confirmed_findings" for point in record._open_points(ws)
    )

    reviewed = findings.update(ws, item["id"], {"auditor_confirmed": True})
    assert reviewed["confirmed_by_kind"] == "auditor"
    assert reviewed["confirmed_by"] is None
    assert not any(
        point["key"] == "run_confirmed_findings"
        for point in record._open_points(workspaces.load_workspace(ws.id))
    )

    cleared = findings.update(
        workspaces.load_workspace(ws.id), item["id"], {"auditor_confirmed": False}
    )
    assert "confirmed_by_kind" not in cleared
    assert "confirmed_at" not in cleared
