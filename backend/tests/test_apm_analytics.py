"""The planning memorandum's data-analytics section is the analysis memo's own.

Held here: the section is the memo's parts, demoted under the memorandum's
heading and fenced with the memo they came from; it is spliced in when the
memorandum is committed; a model reads a digest in its place, never the
exhibits or the memo whole; and the page can tell when the memo has moved, and
take the new one only when asked.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import apm_analytics, workspaces
from app.agent.executors import EXECUTORS, ExecutorRequest
from app.agent.executors.planning import APM_PARENT_REF, ApmExecutorTarget
from app.main import create_app
from app.workspace_transactions import parent_hashes

MEMO = """Three invoices were paid above their order.

## Data received and its limitations

Six tables were received.

| Source table | Records |
| --- | --- |
| invoices | 52 |

## Where the value is

Facilities holds 45% of the value.

```embed
analysis: A-0AC07C55
as: chart
caption: Facilities holds 45.2% of the value
```

## What the analysis found

### 1. Invoices paid above the order

Three invoices exceed their order.

```embed
analysis: A-9FDBC8D0
as: exception_table
```

## Implications for the plan

1. Test the three invoices individually.

## What the data cannot answer

- **Who received the goods?** No receiver column exists.

## Further work required

1. Obtain the receiving log.
"""

APM = """# Audit Planning Memorandum

## Engagement

- Entity: Acme

## Data analytics performed

The analysis is summarised below.

## Key risks and planned response

### Invoices above the order

Test them.
"""


def test_the_section_is_the_memo_s_parts_under_the_memorandum_s_heading():
    spliced = apm_analytics.splice(APM, MEMO)
    section = spliced.split("## Data analytics performed", 1)[1].split("## Key risks", 1)[0]
    assert section.lstrip().startswith(f"<!-- analytics-from-memo:{apm_analytics.memo_sha(MEMO)} -->")
    assert "Three invoices were paid above their order." in section
    # The memo's sections, one level down, with their exhibits and tables.
    assert "### Where the value is" in section and "#### 1. Invoices paid above the order" in section
    assert "analysis: A-0AC07C55" in section and "| invoices | 52 |" in section
    # The analysis' own to-do list is not the plan's.
    assert "Obtain the receiving log" not in section
    # Nothing outside the section moved.
    assert spliced.split("## Data analytics performed")[0] == APM.split("## Data analytics performed")[0]
    assert spliced.split("## Key risks and planned response")[1] == APM.split("## Key risks and planned response")[1]


def test_the_page_knows_when_the_memo_has_moved():
    spliced = apm_analytics.splice(APM, MEMO)
    assert apm_analytics.state(APM, MEMO) == "none"
    assert apm_analytics.state(spliced, MEMO) == "current"
    assert apm_analytics.state(spliced, MEMO + "\nA new paragraph.") == "stale"
    assert apm_analytics.state(spliced, "") == "orphaned"
    # Refreshing replaces the block rather than nesting a second one.
    refreshed = apm_analytics.splice(spliced, MEMO + "\nA new paragraph.")
    assert refreshed.count("analytics-from-memo:") == 1


def test_a_model_reads_a_digest_never_the_exhibits_or_the_memo_whole():
    view = apm_analytics.for_model(apm_analytics.splice(APM, MEMO), {"A-0AC07C55": "Value by department"})
    assert "```embed" not in view and "analysis:" not in view
    assert "Three invoices were paid above their order." in view
    assert "Finding: 1. Invoices paid above the order" in view
    assert "1. Test the three invoices individually." in view
    assert "Who received the goods?" in view
    # The memorandum's own risks are untouched.
    assert "### Invoices above the order" in view
    # A memorandum with written prose there reads as it is.
    assert apm_analytics.for_model(APM) == APM


def _with_memo(name: str) -> workspaces.Workspace:
    ws = workspaces.create_workspace(name)
    ws.update_planning({"context": {"objective": "Assess procurement"}})
    ws.analysis_summary.update({"markdown": MEMO, "cited_analysis_ids": [], "basis_sha1": "x"})
    ws.save()
    return workspaces.load_workspace(ws.id)


def test_the_executor_splices_the_memo_in_at_commit():
    ws = _with_memo("APM with memo")
    request = ExecutorRequest(
        executor_id="planning.apm", capability_id="planning.apm_ready", unit_id="planning.apm",
        proposal={"apm_markdown": APM}, expected_revision=ws.revision,
        expected_parents=parent_hashes(ws, [APM_PARENT_REF]), activity={"artifact_refs": ["planning:apm"]},
    )
    target = ApmExecutorTarget(ws, "run-apm")
    EXECUTORS.execute(request, target)
    stored = target.workspace.planning["apm_markdown"]
    assert apm_analytics.state(stored, MEMO) == "current"
    assert "The analysis is summarised below." not in stored


def test_the_section_is_taken_from_a_new_memo_only_when_asked():
    ws = _with_memo("APM refresh")
    ws.update_planning({"apm_markdown": apm_analytics.splice(APM, MEMO)}, agent=True)
    ws.update_planning({"created_by": "agent"}, agent=True)
    ws.analysis_summary.update({"markdown": MEMO.replace("Three invoices", "Rewritten. Three invoices")})
    ws.save()
    client = TestClient(create_app())
    planning = client.get(f"/api/workspaces/{ws.id}/planning").json()["planning"]
    assert planning["apm_analytics"]["state"] == "stale"

    refreshed = client.post(f"/api/workspaces/{ws.id}/planning/apm/analytics").json()
    assert refreshed["apm_analytics"]["state"] == "current"
    stored = workspaces.load_workspace(ws.id).planning
    assert "Rewritten." in stored["apm_markdown"]
    # Taking the memo's text is not authoring the memorandum.
    assert stored["created_by"] == "agent"


def test_every_planning_turn_reads_the_digest_not_the_exhibits():
    from app.agent.context import adapters

    ws = _with_memo("APM for planning turns")
    ws.update_planning({"apm_markdown": apm_analytics.splice(APM, MEMO)}, agent=True)
    ws = workspaces.load_workspace(ws.id)
    for scope in (adapters.cycle_scope(ws), adapters.rcm_scope(ws), adapters.apm_revision_scope(ws)):
        supplied = [
            str(candidate.source)
            for candidates in scope.candidates.values()
            for candidate in candidates
            if str(candidate.source_ref).startswith("planning:apm") or "Audit Planning Memorandum" in str(candidate.source)
        ]
        assert supplied, scope
        assert all("```embed" not in text and "In summary" in text for text in supplied)
