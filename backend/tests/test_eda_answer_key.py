"""Hold the procurement answer-key scorer honest.

Earlier measurements were rebuilt by hand three times and were wrong once. A
scorer that is itself unverified would only move where the error lives, so the
discriminations it has to make are tested one at a time, and the key is held to
the facilitator guide it is transcribed from.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from eda_answer_key import (
    ANSWER_KEY,
    OUT_OF_SCOPE,
    reach_table,
    score_workspace,
)

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "sample-procurement" / "FACILITATOR_GUIDE.md"


def _workspace(*analyses: dict) -> object:
    """A workspace stub carrying only what the scorer reads.

    No join is declared, so every frame is its own root: the table an analysis
    names is the population its rows belong to.
    """
    return SimpleNamespace(id="stub", analyses=list(analyses), tables=[], joins=[])


def _analysis(
    identifier: str,
    column: str,
    flagged: list[str],
    *,
    table: str = "invoice_data",
    kind: str = "analytics",
    tested: int = 100,
) -> dict:
    """An analysis whose flagged rows hold ``flagged`` in ``column``."""
    return {
        "id": identifier,
        "table": table,
        "kind": kind,
        "spec": {"test": "compare_columns", "params": {}} if kind == "analytics" else {"code": "result = df"},
        **({"outcome_policy": {"mode": "exception_rows"}} if kind == "python" else {}),
        "last_result": {
            "exception_count": len(flagged),
            "tested": tested,
            "verdict": "fail" if flagged else "ok",
        },
        "_evidence": {"frame": {"columns": [column], "rows": [[value] for value in flagged]}}
        if flagged
        else None,
    }


def _score(*analyses: dict):
    return score_workspace(_workspace(*analyses), evidence=lambda analysis: analysis["_evidence"])


def _reached(score) -> set[str]:
    return {item.item.id for item in score.reached}


def _status(score, item_id: str) -> str:
    return next(item.status for item in score.items if item.item.id == item_id)


def test_any_procedure_that_flags_the_records_reaches_the_item():
    """The rows are the conclusion; the spec is only how it was reached.

    Matching by library test and column set missed a completeness check over
    three approval dates that flagged exactly P-08's invoices, and could not see
    a python analysis at all.
    """
    p08 = ["INV2024104", "INV2024131", "INV2024154"]
    assert "P-08" in _reached(_score(_analysis("A-1", "INVOICE_ID", p08)))
    assert "P-08" in _reached(_score(_analysis("A-2", "INVOICE_ID", p08, kind="python")))


def test_the_unit_price_item_is_scoreable():
    """P-11 needs a derived ratio, which only code computes; it now counts."""
    score = _score(_analysis("A-3", "PO_NUMBER", ["PO2024127"], table="po_data", kind="python"))
    assert "P-11" in _reached(score)


def test_the_population_decides_what_a_record_means():
    """A requisition's own PO number on a requisition row is not the PO item.

    A joined frame carries each chain's ids side by side. Without a root, the
    limit check that flagged REQ2024127 scored as the unit-price item, because
    the same row holds PO2024127.
    """
    on_requisitions = _score(
        _analysis("A-4", "PO_NUMBER", ["PO2024127"], table="requisitions")
    )
    assert "P-11" not in _reached(on_requisitions)
    unordered = ["REQ2024124", "REQ2024138", "REQ2024153"]
    assert "P-04" in _reached(_score(_analysis("A-5", "REQUISITION_ID", unordered, table="requisitions")))
    assert "P-04" not in _reached(_score(_analysis("A-6", "REQUISITION_ID", unordered, table="po_data")))


def test_a_value_filter_matches_only_the_side_it_flags():
    """Flagging {Active} names the ten vendors behaving correctly, not P-05."""
    active = [f"V10{n:02d}" for n in (1, 4, 7, 13, 19, 22, 25, 28, 31, 34)]
    assert "P-05" not in _reached(
        _score(_analysis("A-7", "VENDOR_ID", active, table="vendor_master_file", tested=12))
    )
    assert "P-05" in _reached(
        _score(_analysis("A-8", "VENDOR_ID", ["V1010", "V1017"], table="vendor_master_file", tested=12))
    )


def test_some_of_the_records_is_partial_not_reached():
    score = _score(_analysis("A-9", "INVOICE_ID", ["INV2024104"]))
    assert "P-08" not in _reached(score)
    assert _status(score, "P-08") == "partial"
    assert "*partial 1/3*" in reach_table([score], ["x"])


def test_a_capture_among_many_other_rows_is_broad_not_reached():
    """Three over-billed invoices among forty flagged have not been isolated."""
    flagged = ["INV2024106", "INV2024140", "INV2024122"] + [f"INV2025{n:03d}" for n in range(37)]
    score = _score(_analysis("A-10", "INVOICE_ID", flagged, tested=200))
    assert "P-07" not in _reached(score)
    assert _status(score, "P-07") == "broad"


def test_a_saturated_result_is_not_a_hit():
    """A result flagging its whole population establishes nothing about a row."""
    score = _score(_analysis("A-11", "INVOICE_ID", ["INV2024004"], tested=1))
    assert "P-12" not in _reached(score)
    assert _status(score, "P-12") == "saturated"
    row = next(line for line in reach_table([score], ["x"]).splitlines() if "P-12" in line)
    assert row.endswith("| *sat.* |")


def test_a_clean_result_reaches_nothing():
    assert _reached(_score(_analysis("A-12", "INVOICE_ID", []))) == set()


def test_every_key_item_names_its_records():
    for item in ANSWER_KEY:
        assert item.readings, item.id
        for reading in item.readings:
            assert reading.column and reading.ids, item.id


def _guide_records(cell: str) -> set[str]:
    """Record ids a guide cell names, expanding ``REQ/PO/INV2024126``."""
    found: set[str] = set()
    for prefixes, number in re.findall(r"((?:REQ|PO|INV)(?:/(?:REQ|PO|INV))*)(\d{7})", cell):
        found.update(f"{prefix}{number}" for prefix in prefixes.split("/"))
    return found


def test_the_key_is_the_facilitator_guide():
    """Every exception the guide tables is keyed here, with the guide's records.

    The guide is what a run is scored against by hand; a scorer that drifted
    from it would report coverage of a key nobody reads.
    """
    text = GUIDE.read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| (P-\d\d) \|([^\n]*)$", text, re.MULTILINE))
    elsewhere = set(re.findall(r"^\| ([DJ]-\d\d) \|", text, re.MULTILINE))
    assert {item.id for item in ANSWER_KEY} == set(rows)
    assert set(OUT_OF_SCOPE) == elsewhere
    for item in ANSWER_KEY:
        # The records column is the fourth cell; the value column after it can
        # carry figures that look like nothing here.
        cells = rows[item.id].split("|")
        keyed = {
            record
            for reading in item.readings
            if reading.column != "VENDOR_ID"
            for record in reading.ids
        }
        assert keyed == _guide_records(cells[3]), item.id
