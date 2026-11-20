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
    Signature,
    reach_table,
    score_workspace,
)

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "sample-procurement" / "FACILITATOR_GUIDE.md"


def _workspace(*analyses: dict, joins: list[dict] | None = None) -> object:
    """A workspace stub carrying only what the scorer reads."""
    return SimpleNamespace(
        id="stub",
        analyses=list(analyses),
        tables=[{"name": name} for name in ("invoice_data", "requisitions",
                                            "staff_details", "vendor_master_file",
                                            "po_data")],
        joins=list(joins or []),
    )


def _analysis(
    identifier: str,
    test: str,
    params: dict,
    *,
    table: str = "invoice_data",
    exceptions: int = 1,
    tested: int = 100,
) -> dict:
    return {
        "id": identifier,
        "table": table,
        "kind": "analytics",
        "spec": {"test": test, "params": params},
        "last_result": {
            "exception_count": exceptions,
            "tested": tested,
            "verdict": "fail" if exceptions else "ok",
        },
    }


def _reached(score) -> set[str]:
    return {item.item.id for item in score.reached}


def test_a_comparison_matches_in_either_direction():
    """``A ≥ B`` and ``B ≤ A`` are one computation written two ways."""
    forward = _workspace(
        _analysis(
            "A-1", "compare_columns",
            {"column": "INVOICE_DATE", "other": "PO_DATE", "op": "ge"},
            table="invoice_data_po_data_joined",
        )
    )
    reverse = _workspace(
        _analysis(
            "A-2", "compare_columns",
            {"column": "PO_DATE", "other": "INVOICE_DATE", "op": "le"},
            table="invoice_data_po_data_joined",
        )
    )
    assert "P-12" in _reached(score_workspace(forward))
    assert "P-12" in _reached(score_workspace(reverse))


def test_a_value_filter_matches_only_the_side_it_flags():
    """Flagging {Active} is the opposite finding from allowing it.

    Nothing downstream catches this: ``value_filter`` is not in
    ``SATURATION_SENSITIVE_TESTS``, so the ten vendors behaving correctly would
    have scored as P-05 had the matcher ignored ``mode``.
    """
    inverted = _workspace(
        _analysis(
            "A-3", "value_filter",
            {"column": "VENDOR_STATUS", "mode": "flag", "values": ["Active"]},
            table="vendor_master_file", exceptions=10, tested=12,
        )
    )
    correct = _workspace(
        _analysis(
            "A-4", "value_filter",
            {"column": "VENDOR_STATUS", "mode": "allow", "values": ["Active"]},
            table="vendor_master_file", exceptions=2, tested=12,
        )
    )
    assert "P-05" not in _reached(score_workspace(inverted))
    assert "P-05" in _reached(score_workspace(correct))


def test_the_population_decides_what_a_blank_column_means():
    """A blank ``PO_NUMBER`` is P-04 only on the requisitions' own rows.

    The same completeness check over another table's rows names nothing about
    approved requisitions left unordered, so it must not score as that item.
    """
    requisitions = _workspace(
        _analysis("A-5", "completeness", {"columns": ["PO_NUMBER"]},
                  table="requisitions", exceptions=3, tested=55)
    )
    orders = _workspace(
        _analysis("A-6", "completeness", {"columns": ["PO_NUMBER"]},
                  table="po_data", exceptions=3, tested=52)
    )
    assert _reached(score_workspace(requisitions)) == {"P-04"}
    assert _reached(score_workspace(orders)) == set()


def test_an_item_with_two_readings_is_reached_by_either():
    """P-14 is billing before delivery, read on the invoice or the received date."""
    for column in ("INVOICE_DATE", "DATE_RECEIVED"):
        found = _workspace(
            _analysis(
                "A-14", "compare_columns",
                {"column": column, "other": "GRN_DATE", "op": "ge"},
                table="invoice_data_po_data_joined", exceptions=4, tested=52,
            )
        )
        assert "P-14" in _reached(score_workspace(found)), column


def test_a_saturated_comparison_is_not_a_hit():
    """A result flagging its whole population establishes nothing about a row."""
    saturated = _workspace(
        _analysis(
            "A-7", "compare_columns",
            {"column": "INVOICE_DATE", "other": "PO_DATE", "op": "ge"},
            table="invoice_data_po_data_joined", exceptions=52, tested=52,
        )
    )
    score = score_workspace(saturated)
    assert "P-12" not in _reached(score)
    entry = next(item for item in score.items if item.item.id == "P-12")
    assert entry.saturated
    assert reach_table([score], ["x"]).count("*sat.*") == 1


def test_a_clean_result_reaches_nothing():
    """A test that ran and found nothing is a real answer and is not the item."""
    clean = _workspace(
        _analysis(
            "A-9", "compare_columns",
            {"column": "INVOICE_DATE", "other": "PO_DATE", "op": "ge"},
            table="invoice_data_po_data_joined", exceptions=0, tested=52,
        )
    )
    assert _reached(score_workspace(clean)) == set()


def test_unscoreable_items_are_reported_not_counted_absent():
    score = score_workspace(_workspace())
    assert {item.id for item in score.unscoreable} == {"P-11"}
    assert all(item.item.id != "P-11" for item in score.items)


def test_every_key_item_is_either_signed_or_explained():
    for item in ANSWER_KEY:
        assert bool(item.signatures) != bool(item.unscoreable), item.id
        for signature in item.signatures:
            assert isinstance(signature, Signature)
            if signature.test == "value_filter":
                # Established above: an unmoded value_filter matcher scores the
                # inverse finding as a hit.
                assert signature.mode in {"flag", "allow"}, item.id


def test_the_key_is_the_facilitator_guide():
    """Every exception the guide tables is keyed here, and nothing else is.

    The guide is what a run is scored against by hand; a scorer that drifted
    from it would report coverage of a key nobody reads.
    """
    text = GUIDE.read_text(encoding="utf-8")
    tabled = set(re.findall(r"^\| (P-\d\d) \|", text, re.MULTILINE))
    elsewhere = set(re.findall(r"^\| ([DJ]-\d\d) \|", text, re.MULTILINE))
    assert {item.id for item in ANSWER_KEY} == tabled
    assert set(OUT_OF_SCOPE) == elsewhere
