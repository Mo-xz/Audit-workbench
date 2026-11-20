"""Hold the Appendix A scorer honest.

The scorer is the EDA forward plan's regression gate. Earlier measurements were
rebuilt by hand three times and were wrong once. A scorer that is itself
unverified would only move where the error lives, so the discriminations it has
to make are tested one at a time.
"""

from __future__ import annotations

from types import SimpleNamespace

from eda_answer_key import ANSWER_KEY, Signature, reach_table, score_workspace


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
    assert "A16" in _reached(score_workspace(forward))
    assert "A16" in _reached(score_workspace(reverse))


def test_a_value_filter_matches_only_the_side_it_flags():
    """Flagging {Active} is the opposite finding from allowing it.

    Nothing downstream catches this: ``value_filter`` is not in
    ``SATURATION_SENSITIVE_TESTS``, so 37 of 39 vendors behaving correctly
    would have scored as A23 had the matcher ignored ``mode``.
    """
    inverted = _workspace(
        _analysis(
            "A-3", "value_filter",
            {"column": "VENDOR_STATUS", "mode": "flag", "values": ["Active"]},
            table="vendor_master_file", exceptions=37, tested=39,
        )
    )
    correct = _workspace(
        _analysis(
            "A-4", "value_filter",
            {"column": "VENDOR_STATUS", "mode": "allow", "values": ["Active"]},
            table="vendor_master_file", exceptions=2, tested=39,
        )
    )
    assert "A23" not in _reached(score_workspace(inverted))
    assert "A23" in _reached(score_workspace(correct))


def test_the_population_separates_two_items_reading_one_column():
    """A21 and A29 are the same spec over different rows.

    ``BANK_ACCOUNT_NUMBER`` duplicates on the vendor master and on the staff
    master are one computation and two findings, which is exactly the
    distinction ``analysis_semantic_id`` draws with ``frame_root``.
    """
    vendors = _workspace(
        _analysis("A-5", "duplicates", {"columns": ["BANK_ACCOUNT_NUMBER"]},
                  table="vendor_master_file", exceptions=4, tested=39)
    )
    staff = _workspace(
        _analysis("A-6", "duplicates", {"columns": ["BANK_ACCOUNT_NUMBER"]},
                  table="staff_details", exceptions=6, tested=52)
    )
    assert _reached(score_workspace(vendors)) == {"A21"}
    assert _reached(score_workspace(staff)) == {"A29"}


def test_a_saturated_comparison_is_not_a_hit():
    """A result flagging its whole population establishes nothing about a row."""
    saturated = _workspace(
        _analysis(
            "A-7", "compare_columns",
            {"column": "INVOICE_DATE", "other": "PO_DATE", "op": "ge"},
            table="invoice_data_po_data_joined", exceptions=96, tested=96,
        )
    )
    score = score_workspace(saturated)
    assert "A16" not in _reached(score)
    entry = next(item for item in score.items if item.item.id == "A16")
    assert entry.saturated
    assert reach_table([score], ["x"]).count("*sat.*") == 1


def test_referential_is_exempt_from_saturation():
    """A30 is a legitimate 96-of-96 finding; a blanket rule would delete it."""
    total = _workspace(
        _analysis(
            "A-8", "referential",
            {"column": "BUYER_ID", "lookup_table": "staff_details",
             "lookup_column": "STAFF_ID"},
            table="po_data", exceptions=96, tested=96,
        )
    )
    assert "A30" in _reached(score_workspace(total))


def test_a_clean_result_reaches_nothing():
    """A test that ran and found nothing is a real answer and is not the item."""
    clean = _workspace(
        _analysis(
            "A-9", "compare_columns",
            {"column": "INVOICE_DATE", "other": "PO_DATE", "op": "ge"},
            table="invoice_data_po_data_joined", exceptions=0, tested=96,
        )
    )
    assert _reached(score_workspace(clean)) == set()


def test_a_reference_resolving_nowhere_scores_whichever_master_it_names():
    """A30's finding is the column, not the lookup.

    These buyer codes resolve in no imported master, so every candidate fails
    identically and which one a spec names is not something the data decides.
    Two runs found the same 96 rows and named different masters; a matcher tied
    to ``staff_details`` scored one of them absent.
    """
    for table, key in (
        ("staff_details", "STAFF_ID"),
        ("requisitions", "REQUISITION_ID"),
        ("invoice_data", "INVOICE_ID"),
    ):
        found = _workspace(
            _analysis(
                "A-30", "referential",
                {"column": "BUYER_ID", "lookup_table": table, "lookup_column": key},
                table="po_data", exceptions=96, tested=96,
            )
        )
        assert "A30" in _reached(score_workspace(found)), table


def test_unscoreable_items_are_reported_not_counted_absent():
    score = score_workspace(_workspace())
    assert {item.id for item in score.unscoreable} == {"A25", "A26", "A33"}
    assert all(item.item.id not in {"A25", "A26", "A33"} for item in score.items)


def test_every_key_item_is_either_signed_or_explained():
    for item in ANSWER_KEY:
        assert bool(item.signatures) != bool(item.unscoreable), item.id
        for signature in item.signatures:
            assert isinstance(signature, Signature)
            if signature.test == "value_filter":
                # Established above: an unmoded value_filter matcher scores the
                # inverse finding as a hit.
                assert signature.mode in {"flag", "allow"}, item.id
