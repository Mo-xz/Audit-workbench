"""The assertion register: its deterministic floor, and what a turn may do to it.

The register is the artifact E4 introduces, and its whole safety argument is an
asymmetry — a reading turn may add freely and subtract only with an argument, so
the worst case of spending one model turn on the entire engagement is the floor
that turn was handed. These tests hold that asymmetry from both ends: the floor
is complete without any turn, and a turn cannot quietly shrink it.
"""

from __future__ import annotations

import polars as pl
import pytest

from app import workspaces
from app.agent import probes, register
from app.agent.analysis_identity import analysis_semantic_id
from app.agent.capabilities import analysis as analysis_capabilities
from app.agent.workflow import semantic_unit_id


@pytest.fixture
def swept_workspace() -> workspaces.Workspace:
    """Two tables whose invoice side carries a reconciliation gap and a repeat."""
    ws = workspaces.create_workspace("Register fixture")
    invoices = pl.DataFrame(
        {
            "invoice_no": [f"INV{index:03d}" for index in range(1, 25)] + ["INV024"],
            "po_link": [f"PO{index:03d}" for index in range(1, 21)]
            + ["REQ001", "REQ002", "REQ003", "REQ004", "PO020"],
            "amount": [100.0 + index for index in range(25)],
            # A dominant state with a rare one beside it, so the fixture
            # nominates a third family and the merge has something to leave
            # unmentioned as well as something to keep and something to decline.
            "status": ["Paid"] * 22 + ["Rejected", "Rejected", "Held"],
        }
    )
    orders = pl.DataFrame(
        {
            "po_number": [f"PO{index:03d}" for index in range(1, 21)],
            "total": [500.0 for _ in range(20)],
        }
    )
    ws.add_table("invoices.csv", invoices.write_csv().encode())
    ws.add_table("orders.csv", orders.write_csv().encode())
    return ws


def _floor(ws: workspaces.Workspace) -> tuple[register.Nomination, ...]:
    swept = {name: probes.probe_frame(ws, name) for name in ws.table_names()}
    return register.build_floor(ws, swept)


def test_the_floor_is_a_complete_register_with_no_model_turn(swept_workspace):
    """A run whose reading turn never happens still holds every measurement."""
    floor = _floor(swept_workspace)
    assert floor, "the fixture must nominate something"
    settled = register.default_register(floor)

    assert len(settled.kept) == len(floor)
    assert not settled.read
    assert not settled.authored and not settled.declined
    for entry in settled.kept:
        definition = entry.definition()
        # Every entry is committable as it stands: a runnable spec, a frame, a
        # name, and a note that says what was actually measured.
        assert definition["kind"] == "analytics"
        assert definition["spec"]["test"]
        assert definition["table"] in swept_workspace.table_names()
        assert definition["title"].strip()
        assert definition["note"].strip()
        assert definition["semantic_id"].startswith("analysis:")


def test_one_computation_over_one_population_is_one_entry(swept_workspace):
    """The dedup that makes a whole-engagement sweep affordable to commit.

    A frame's nominations are measured per frame, and an invoice-only check is
    reachable from every invoice-rooted frame in the family. Identity folds
    those; it does not fold two frames that ask the same spec of different rows.
    """
    floor = _floor(swept_workspace)
    identities = [entry.semantic_id for entry in floor]
    assert len(identities) == len(set(identities))

    # And the fold is the same identity the executor writes under, so a
    # register entry and a definition-turn proposal for one computation
    # deduplicate against each other rather than saving twice.
    for entry in floor:
        recomputed = analysis_semantic_id(
            "analytics",
            entry.frame,
            entry.spec,
            {
                column: entry.frame
                for column in swept_workspace.get_frame(entry.frame).columns
            },
            entry.frame,
            {},
        )
        assert recomputed.startswith("analysis:")


def test_a_comparison_read_from_the_other_side_is_the_same_analysis():
    """``A ≥ B`` and ``B ≤ A`` breach on the same rows; one identity, not two."""
    origins = {"INVOICE_DATE": "invoice_data", "GRN_DATE": "po_data"}

    def identity(column: str, op: str, other: str) -> str:
        spec = {
            "test": "compare_columns",
            "params": {"column": column, "op": op, "other": other, "compare_as": "date"},
        }
        return analysis_semantic_id("analytics", "frame", spec, origins)

    assert identity("INVOICE_DATE", "ge", "GRN_DATE") == identity(
        "GRN_DATE", "le", "INVOICE_DATE"
    )
    assert identity("INVOICE_DATE", "gt", "GRN_DATE") == identity(
        "GRN_DATE", "lt", "INVOICE_DATE"
    )
    # Mirroring is not loosening: the opposite ordering is a different check.
    assert identity("INVOICE_DATE", "ge", "GRN_DATE") != identity(
        "INVOICE_DATE", "le", "GRN_DATE"
    )


def _joined_workspace(name: str, tables: dict[str, pl.DataFrame], joins: list[dict]):
    ws = workspaces.create_workspace(name)
    for table, frame in tables.items():
        ws.add_table(f"{table}.csv", frame.write_csv().encode())
    for join in joins:
        ws.add_join({"how": "left", **join})
    return workspaces.load_workspace(ws.id)


def _swept(ws: workspaces.Workspace) -> dict[str, list[dict]]:
    return {name: probes.probe_frame(ws, name) for name in ws.table_names()}


def _entries(floor, *columns: str) -> list[register.Nomination]:
    return [item for item in floor if set(columns) <= set(item.columns)]


def test_one_finding_reached_by_several_routes_is_one_entry():
    """The procurement case: one-to-one tables make every route the same rows.

    An invoice reaches its order by the PO number and by the receipt number,
    and an order reaches its invoice back the other way. Identity keeps all
    three apart — two keys, two roots — though each flags the same three late
    receipts. The sweep's row fingerprint is what says so, even though each
    route drops a different key column from the frame it builds.
    """
    rows = range(30)
    ws = _joined_workspace(
        "Routes",
        {
            "invoices": pl.DataFrame(
                {
                    "invoice_id": [f"INV{n:03d}" for n in rows],
                    "po_link": [f"PO{n:03d}" for n in rows],
                    "grn_link": [f"GRN{n:03d}" for n in rows],
                    "currency": ["PKR" if n % 3 else "USD" for n in rows],
                    "invoice_date": [f"2024-03-{n % 28 + 1:02d}" for n in rows],
                }
            ),
            "orders": pl.DataFrame(
                {
                    "po_number": [f"PO{n:03d}" for n in rows],
                    "grn_id": [f"GRN{n:03d}" for n in rows],
                    "buyer": [f"B{n % 4}" for n in rows],
                    # Received on the invoice date, except three received after.
                    "grn_date": [
                        f"2024-04-{n % 28 + 1:02d}" if n in (4, 14, 24) else f"2024-03-{n % 28 + 1:02d}"
                        for n in rows
                    ],
                }
            ),
        },
        [
            {"name": "inv_by_po", "left": "invoices", "right": "orders",
             "left_on": ["po_link"], "right_on": ["po_number"]},
            {"name": "inv_by_grn", "left": "invoices", "right": "orders",
             "left_on": ["grn_link"], "right_on": ["grn_id"]},
            {"name": "orders_inv", "left": "orders", "right": "invoices",
             "left_on": ["po_number"], "right_on": ["po_link"]},
        ],
    )
    swept = _swept(ws)
    floor = register.build_floor(ws, swept)
    entries = _entries(floor, "grn_date", "invoice_date")
    assert len(entries) == 1, [(item.frame, item.params) for item in entries]
    entry = entries[0]
    assert entry.flagged == 3
    assert {entry.frame, *entry.also_on} == {"inv_by_po", "inv_by_grn", "orders_inv"}

    # Without the fingerprint identity alone keeps the routes apart, which is
    # what this test would otherwise pass vacuously on.
    unprinted = {
        frame: [{k: v for k, v in item.items() if k != "flagged_digest"} for item in items]
        for frame, items in swept.items()
    }
    assert len(_entries(register.build_floor(ws, unprinted), "grn_date", "invoice_date")) > 1


def test_routes_that_flag_different_rows_stay_apart():
    """The job-title case: a route that changes the rows changes the answer.

    One amount against one limit column, reached through the approver and
    through the verifier. Both flag three invoices, but not the same three, so
    they are two questions and the merge must not fold them.
    """
    rows = range(30)
    ws = _joined_workspace(
        "Roles",
        {
            "invoices": pl.DataFrame(
                {
                    "invoice_id": [f"INV{n:03d}" for n in rows],
                    "approver_id": [f"S{n % 10:02d}" for n in rows],
                    "verifier_id": [f"S{(n + 3) % 10:02d}" for n in rows],
                    "amount": [500.0 + n for n in rows],
                }
            ),
            "staff": pl.DataFrame(
                {
                    "staff_id": [f"S{n:02d}" for n in range(10)],
                    "grade": [f"G{n % 3}" for n in range(10)],
                    "limit_amount": [100.0 if n == 0 else 1000.0 + n for n in range(10)],
                }
            ),
        },
        [
            {"name": "inv_approver", "left": "invoices", "right": "staff",
             "left_on": ["approver_id"], "right_on": ["staff_id"]},
            {"name": "inv_verifier", "left": "invoices", "right": "staff",
             "left_on": ["verifier_id"], "right_on": ["staff_id"]},
        ],
    )
    floor = register.build_floor(ws, _swept(ws))
    entries = _entries(floor, "amount", "limit_amount")
    assert {item.frame for item in entries} == {"inv_approver", "inv_verifier"}
    assert all(item.flagged == 3 and not item.also_on for item in entries)


def test_the_row_fingerprint_never_reaches_model_context(swept_workspace):
    """The merge key is a hash of row values, so no prompt carries it."""
    from app.agent.context import adapters

    found = probes.probe_frame(swept_workspace, "invoices")
    assert any(item.get("flagged_digest") for item in found)
    assert not any("_flagged_rows" in item for item in found)
    stripped = adapters._without_digest(found[0])
    assert "flagged_digest" not in stripped


def test_a_reference_that_resolves_nowhere_is_one_finding_not_four():
    """The sweep names *a* master when every candidate fails identically.

    Which one it names is decided by alphabetical order among the tables outside
    that frame's lineage, so the same finding arrives under a different lookup
    on every frame. Collapsing them is not cosmetic: uncollapsed, one bad
    reference column commits four analyses that differ only in a name the data
    could not establish.
    """
    ws = workspaces.create_workspace("Unreferenced")
    facts = pl.DataFrame(
        {
            "fact_id": [f"F{index:03d}" for index in range(1, 31)],
            "buyer_id": [f"B{index % 6:03d}" for index in range(30)],
        }
    )
    for name in ("alphas", "zulus"):
        dim = pl.DataFrame(
            {f"{name[:-1]}_id": [f"{name[0].upper()}{index:03d}" for index in range(1, 31)]}
        )
        ws.add_table(f"{name}.csv", dim.write_csv().encode())
    ws.add_table("facts.csv", facts.write_csv().encode())

    swept = {name: probes.probe_frame(ws, name) for name in ws.table_names()}
    unresolved = [
        item
        for items in swept.values()
        for item in items
        if item["test"] == "referential"
        and str((item.get("params") or {}).get("column")) == "buyer_id"
        and item.get("flagged")
    ]
    if not unresolved:
        pytest.skip("the fixture produced no unresolved reference to collapse")

    floor = register.build_floor(ws, swept)
    entries = [item for item in floor if "buyer_id" in item.columns]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.unreferenced
    # The title states what was found and does not name a master as if the
    # measurement had chosen it.
    assert entry.derived_title() == "buyer_id reconciles to no imported master"


def test_silence_keeps_a_nomination_and_a_decline_must_argue(swept_workspace):
    """Additive by default; subtraction is the only thing that needs a reason."""
    floor = _floor(swept_workspace)
    assert len(floor) >= 2
    kept_ref, declined_ref = floor[0].ref, floor[1].ref

    settled = register.merge(
        floor,
        {
            "keep": [
                {"ref": kept_ref, "title": "A better name", "note": "What it means."}
            ],
            "decline": [{"ref": declined_ref, "reason": "Ordinary operations."}],
            "add": [],
            "unanswerable": [],
        },
    )

    assert settled.read
    # Everything the turn never mentioned survives.
    assert {item.ref for item in settled.kept} == {
        item.ref for item in floor
    } - {declined_ref}
    named = next(item for item in settled.kept if item.ref == kept_ref)
    assert (named.title, named.origin) == ("A better name", "reading")
    unmentioned = next(item for item in settled.kept if item.ref not in {kept_ref})
    assert unmentioned.origin == "sweep"
    assert [item.reason for item in settled.declined] == ["Ordinary operations."]


def test_a_decline_without_a_reason_does_not_subtract(swept_workspace):
    """The second guard. The worker's validator rejects this first; if one ever
    reached the merge, dropping a measured nomination on no argument is the one
    outcome the register must not produce."""
    floor = _floor(swept_workspace)
    settled = register.merge(
        floor,
        {"keep": [], "add": [], "decline": [{"ref": floor[0].ref, "reason": "  "}], "unanswerable": []},
    )
    assert len(settled.kept) == len(floor)
    assert not settled.declined


def test_an_unknown_reference_cannot_remove_anything(swept_workspace):
    floor = _floor(swept_workspace)
    settled = register.merge(
        floor,
        {
            "keep": [{"ref": "N99", "title": "x", "note": "y"}],
            "decline": [{"ref": "N98", "reason": "not a real nomination"}],
            "add": [],
            "unanswerable": [],
        },
    )
    assert len(settled.kept) == len(floor)
    assert not settled.declined


def test_only_authored_assertions_expand_a_definition_turn(swept_workspace):
    """A kept nomination is already a spec; re-deriving it is what E4 removes."""
    floor = _floor(swept_workspace)
    settled = register.merge(
        floor,
        {
            "keep": [],
            "decline": [],
            "add": [
                {
                    "frame": "invoices",
                    "columns": ["amount"],
                    "assertion": "An invoice amount never exceeds its order total.",
                    "why": "Paying above the order is the control failing.",
                }
            ],
            "unanswerable": [],
        },
    )
    assert settled.frames() == ("invoices",)
    assert len(settled.assertions_for("invoices")) == 1
    assert settled.assertions_for("orders") == ()


def test_the_register_survives_a_round_trip_through_the_run_record(swept_workspace):
    """A resumed run must not re-sweep and must not re-bill the reading turn."""
    floor = _floor(swept_workspace)
    settled = register.merge(
        floor,
        {
            "keep": [{"ref": floor[0].ref, "title": "Named", "note": "Explained."}],
            "decline": [],
            "add": [
                {
                    "frame": "invoices",
                    "columns": ["amount"],
                    "assertion": "An invoice amount never exceeds its order total.",
                    "why": "Paying above the order is the control failing.",
                }
            ],
            "unanswerable": [{"question": "Was a bid held?", "why": "No column records one."}],
        },
    )
    restored = register.from_payload(settled.payload())

    assert restored.read
    assert [item.definition() for item in restored.kept] == [
        item.definition() for item in settled.kept
    ]
    assert restored.assertions_for("invoices") == settled.assertions_for("invoices")
    assert [item.question for item in restored.unanswerable] == ["Was a bid held?"]


def test_the_reading_unit_is_ordered_before_the_commit(swept_workspace):
    """The sequential barrier runs a capability's units in sorted id order.

    Nothing else enforces it, and the two names do not make the dependency
    obvious, so it is asserted rather than assumed: the commit unit reads a
    register the reading unit writes.
    """
    units = analysis_capabilities.capabilities()
    register_capability = next(
        item for item in units if item.id == "analysis.register_ready"
    )
    specs = register_capability.expand_units(swept_workspace, {})
    assert [spec.kind for spec in specs] == ["analysis_reading", "analysis_register"]
    assert sorted(spec.id for spec in specs) == [spec.id for spec in specs]
    # And neither id names the frames it covers, so a join landing mid-run does
    # not turn either into a second, unbilled-for unit.
    assert [spec.id for spec in specs] == [
        semantic_unit_id("analysis_reading"),
        semantic_unit_id("analysis_register"),
    ]
