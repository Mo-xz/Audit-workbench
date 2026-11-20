"""The procurement sample's answer key, scored against a workspace's analyses.

The key is the Class 1 table (P-01 to P-14) of
``docs/sample-procurement/FACILITATOR_GUIDE.md``: the exceptions visible in the
pack's six workbooks. Earlier run-by-run tables were rebuilt by hand three times
and were wrong once. This module is the rebuild, once, in code: an answer key of
*computations*, a scorer over a workspace's saved analyses, and a rendering of
the same reach table.

It scores the exploratory analyses only. Whether a run carried an item on into
a finding and the report is the guide's own scoring, made against the findings;
the guide's document-only and judgement items (``OUT_OF_SCOPE``) are never
reachable by an analysis at all. It replaces an earlier A01-A33 key, written for
a larger edition of the same data whose records this pack does not hold.

Two rules govern scoring and are intentionally enforced here rather than left to
documentation:

* **Match the computation, never the title.** Titles move between runs and the
  test a frame ran does not. A key item names a test id and the columns that
  identify it; a ``compare_columns`` pair is unordered, because ``A ≥ B`` and
  ``B ≤ A`` are one computation written two ways.
* **A saturated hit is not a hit.** A result flagging its whole population
  establishes nothing about any row in it, and the application already says so
  — so the scorer asks ``analysis_results.uninformative_reason`` rather than
  keeping a second opinion. That function exempts ``referential`` deliberately,
  since a reference that resolves nowhere can legitimately fail every row.

Where an item's population matters the key names a ``root`` — the base table the
frame's rows are rows *of*. ``PO_NUMBER`` blank on a requisition is P-04, an
approved requisition never ordered; the same column read through another table's
rows is not. It is the same distinction ``analysis_semantic_id`` draws, for the
same reason.

P-11 carries no signature: it needs a unit price derived within each item, which
no library test computes. It is reported as unscoreable rather than silently
counted absent, because "no procedure can express this" and "no procedure was
written" are different failures.

Run it directly to score a workspace::

    .venv\\Scripts\\python.exe backend\\tests\\eda_answer_key.py Workspaces\\Users\\local\\Workspaces\\procurement
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__":  # pragma: no cover - direct-invocation convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import analysis_results
from app.agent import joins as join_diagnostics
from app.workspaces import Workspace


# Parameter names that carry a spec's identifying columns, per test family. A
# spec is identified by the set of columns it reads, so the scorer collects them
# without needing to know each test's own argument order.
_COLUMN_PARAMS = ("column", "other", "columns", "date_column", "amount_column")


@dataclass(frozen=True)
class Signature:
    """One computation, in the terms that make two runs comparable.

    ``columns`` is a frozen set rather than a sequence: a comparison names two
    columns and the direction it names them in is a property of how the model
    worded it, not of what was measured.
    """

    test: str
    columns: frozenset[str] = frozenset()
    lookup: tuple[str, str] | None = None
    values: frozenset[str] = frozenset()
    #: ``value_filter`` only. Which side of the named set the spec flags, and it
    #: is never optional: ``flag`` on {Active} and ``allow`` on {Active} are
    #: opposite findings over one column, and the second is 37 of 39 vendors
    #: behaving correctly. ``value_filter`` is not saturation-sensitive, so
    #: nothing downstream would have caught the inversion either.
    mode: str = ""

    def matches(self, spec: Mapping[str, object]) -> bool:
        if str(spec.get("test") or "") != self.test:
            return False
        params = spec.get("params")
        params = params if isinstance(params, Mapping) else {}
        if self.columns and _spec_columns(params) != self.columns:
            return False
        if self.lookup is not None:
            found = (
                str(params.get("lookup_table") or ""),
                str(params.get("lookup_column") or ""),
            )
            if found != self.lookup:
                return False
        if self.mode and str(params.get("mode") or "") != self.mode:
            return False
        if self.values:
            named = {str(value) for value in params.get("values") or ()}
            if named != self.values:
                return False
        return True


def _spec_columns(params: Mapping[str, object]) -> frozenset[str]:
    found: set[str] = set()
    for name in _COLUMN_PARAMS:
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            found.add(value.strip())
        elif isinstance(value, (list, tuple)):
            found.update(str(item).strip() for item in value if str(item).strip())
    return frozenset(found)


@dataclass(frozen=True)
class KeyItem:
    """One answer-key item and the computation that would reach it."""

    id: str
    label: str
    signatures: tuple[Signature, ...] = ()
    #: The base table the frame's rows must be rows of, where the population is
    #: what distinguishes this item from another reading the same columns.
    root: str | None = None
    #: Why no signature can express this one. Present exactly when signatures is
    #: empty, and reported rather than scored.
    unscoreable: str = ""


def _compare(*columns: str) -> Signature:
    return Signature("compare_columns", frozenset(columns))


def _flags(column: str, *values: str) -> Signature:
    """A ``value_filter`` that flags the rows holding one of ``values``."""
    return Signature(
        "value_filter", frozenset({column}), values=frozenset(values), mode="flag"
    )


def _allows(column: str, *values: str) -> Signature:
    """A ``value_filter`` that flags the rows holding anything but ``values``."""
    return Signature(
        "value_filter", frozenset({column}), values=frozenset(values), mode="allow"
    )


# The key. Item text is the Class 1 table of
# ``docs/sample-procurement/FACILITATOR_GUIDE.md``; each signature is a
# computation verified against the six workbooks in ``docs/sample-procurement/data``.
ANSWER_KEY: tuple[KeyItem, ...] = (
    KeyItem(
        "P-01",
        "requisition verified by its own requester",
        (_compare("REQUESTER_ID", "VERIFIED_BY_ID"),),
        root="requisitions",
    ),
    KeyItem(
        "P-02",
        "requisition approved above the approver's limit",
        (_compare("MAX_APPROVAL_AMOUNT", "ESTIMATED_TOTAL_COST"),),
        root="requisitions",
    ),
    KeyItem(
        "P-03",
        "procurement approval not recorded",
        (
            Signature("completeness", frozenset({"APPROVED_BY_ID"})),
            Signature("completeness", frozenset({"APPROVAL_DATE"})),
        ),
        root="requisitions",
    ),
    KeyItem(
        "P-04",
        "approved requisition neither ordered nor withdrawn",
        (Signature("completeness", frozenset({"PO_NUMBER"})),),
        root="requisitions",
    ),
    KeyItem(
        "P-05",
        "vendor not Active, yet ordered from and paid",
        # Unrooted on purpose: the status is a property of the vendor, and a
        # filter on the master names the same two vendors the chain reaches.
        (
            _allows("VENDOR_STATUS", "Active"),
            _flags("VENDOR_STATUS", "Inactive", "Under Review"),
            _flags("VENDOR_STATUS", "Under Review"),
            _flags("VENDOR_STATUS", "Inactive"),
        ),
    ),
    KeyItem(
        "P-06",
        "invoice settled with no goods receipt reference",
        (Signature("completeness", frozenset({"GRN_ID_LINK"})),),
        root="invoice_data",
    ),
    KeyItem(
        "P-07",
        "invoice amount above the PO total",
        (_compare("INVOICE_AMOUNT", "PO_TOTAL_AMOUNT"),),
    ),
    KeyItem(
        "P-08",
        "invoice paid with no approval recorded",
        (
            Signature("completeness", frozenset({"SUPERVISOR_APPROVAL_ID"})),
            Signature("completeness", frozenset({"SUPERVISOR_APPROVAL_DATE"})),
        ),
        root="invoice_data",
    ),
    KeyItem(
        "P-09",
        "invoice approved above the approver's limit",
        (_compare("INVOICE_AMOUNT", "MAX_APPROVAL_AMOUNT"),),
        root="invoice_data",
    ),
    KeyItem(
        "P-10",
        "payment released before the goods receipt",
        (_compare("PAYMENT_DATE", "GRN_DATE"),),
    ),
    KeyItem(
        "P-11",
        "unit price far above every other order for the same item",
        unscoreable=(
            "needs a unit price derived as PO total over quantity and compared "
            "within each item; no library test computes the ratio, and a python "
            "spec's identity is its code, which no signature can match"
        ),
    ),
    KeyItem("P-12", "invoice dated before its PO", (_compare("INVOICE_DATE", "PO_DATE"),)),
    KeyItem(
        "P-13",
        "invoice received before its own invoice date",
        (_compare("DATE_RECEIVED", "INVOICE_DATE"),),
    ),
    KeyItem(
        "P-14",
        "invoice dated or received before the goods receipt",
        (
            _compare("INVOICE_DATE", "GRN_DATE"),
            _compare("DATE_RECEIVED", "GRN_DATE"),
        ),
    ),
)

# Document-only and judgement items (Classes 2 and 3 of the guide), outside the
# EDA's scope entirely: no table carries them.
OUT_OF_SCOPE = ("D-01", "D-02", "D-03", "D-04", "D-05", "J-01", "J-02", "J-03")


@dataclass(frozen=True)
class Hit:
    """One saved analysis that reaches a key item."""

    analysis_id: str
    table: str
    root: str
    exceptions: int
    tested: int | None

    @property
    def fraction(self) -> str:
        return f"{self.exceptions}/{self.tested}" if self.tested else str(self.exceptions)


@dataclass(frozen=True)
class ItemScore:
    item: KeyItem
    hits: tuple[Hit, ...] = ()
    #: Analyses matching the signature that were rejected, and why.
    rejected: tuple[tuple[str, str], ...] = ()

    @property
    def reached(self) -> bool:
        return bool(self.hits)

    @property
    def saturated(self) -> bool:
        return not self.hits and bool(self.rejected)


@dataclass(frozen=True)
class Score:
    workspace_id: str
    run_id: str | None
    items: tuple[ItemScore, ...]
    analyses: int
    #: Key items whose signature no run can express (P-11).
    unscoreable: tuple[KeyItem, ...] = field(default=())

    @property
    def reached(self) -> tuple[ItemScore, ...]:
        return tuple(item for item in self.items if item.reached)

    @property
    def addressable(self) -> int:
        return len(self.items)


def _analysis_root(workspace: Workspace, table: str) -> str:
    try:
        return join_diagnostics.frame_root(workspace, table)
    except Exception:  # noqa: BLE001 - an unresolvable frame is its own root
        return table


def score_workspace(workspace: Workspace, *, run_id: str | None = None) -> Score:
    """Score every saved analysis in a workspace against the answer key.

    ``run_id`` restricts scoring to one agent run, which is what makes two runs
    in the same workspace comparable. With it absent every saved analysis
    counts, including any the auditor wrote — the same basis used for the pinned
    measurement, since the measured runs are unattended and author everything
    they hold.
    """
    analyses = [
        item
        for item in workspace.analyses
        if run_id is None or str(item.get("agent_run_id") or "") == run_id
    ]
    scored: list[ItemScore] = []
    unscoreable: list[KeyItem] = []
    for key in ANSWER_KEY:
        if not key.signatures:
            unscoreable.append(key)
            continue
        hits: list[Hit] = []
        rejected: list[tuple[str, str]] = []
        for analysis in analyses:
            spec = analysis.get("spec")
            spec = spec if isinstance(spec, Mapping) else {}
            if not any(signature.matches(spec) for signature in key.signatures):
                continue
            table = str(analysis.get("table") or "")
            root = _analysis_root(workspace, table)
            if key.root is not None and root != key.root:
                continue
            result = analysis.get("last_result")
            result = result if isinstance(result, Mapping) else {}
            exceptions = int(result.get("exception_count") or 0)
            tested = result.get("tested")
            tested = int(tested) if isinstance(tested, int) else None
            if not exceptions:
                # A clean result is a test that ran and found nothing. It is a
                # real answer about the data and it is not this item.
                continue
            reason = analysis_results.uninformative_reason(
                analysis,
                exception_count=exceptions,
                denominator=tested,
                rate=(exceptions / tested) if tested else None,
            )
            identifier = str(analysis.get("id") or "")
            if reason:
                rejected.append((identifier, reason))
                continue
            hits.append(Hit(identifier, table, root, exceptions, tested))
        hits.sort(key=lambda hit: (-hit.exceptions, hit.analysis_id))
        scored.append(ItemScore(key, tuple(hits), tuple(rejected)))
    return Score(
        workspace_id=str(workspace.id),
        run_id=run_id,
        items=tuple(scored),
        analyses=len(analyses),
        unscoreable=tuple(unscoreable),
    )


def reach_table(scores: Sequence[Score], labels: Sequence[str]) -> str:
    """Render the comparable reach table across one or more scored runs."""
    header = "| item | " + " | ".join(labels) + " |"
    rule = "|---|" + "|".join("---:" for _ in labels) + "|"
    lines = [header, rule]
    for index, key in enumerate(scores[0].items):
        cells = []
        for score in scores:
            entry = score.items[index]
            if entry.reached:
                cells.append(entry.hits[0].fraction)
            elif entry.saturated:
                cells.append("*sat.*")
            else:
                cells.append("—")
        lines.append(f"| {key.item.id} {key.item.label} | " + " | ".join(cells) + " |")
    totals = " | ".join(f"**{len(score.reached)}**" for score in scores)
    lines.append(f"| **Reached** | {totals} |")
    return "\n".join(lines)


def _report(score: Score, label: str) -> str:
    lines = [
        f"{label}: {len(score.reached)} of {score.addressable} scoreable items "
        f"from {score.analyses} analyses"
    ]
    missing = [item.item.id for item in score.items if not item.reached]
    if missing:
        lines.append("  absent: " + ", ".join(missing))
    saturated = [item.item.id for item in score.items if item.saturated]
    if saturated:
        lines.append("  rejected as saturated: " + ", ".join(saturated))
    if score.unscoreable:
        lines.append(
            "  not scoreable by signature: "
            + ", ".join(item.id for item in score.unscoreable)
        )
    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:  # pragma: no cover - CLI
    if not argv:
        print(__doc__)
        return 2
    scores = []
    labels = []
    for path in argv:
        root = Path(path).resolve()
        score = score_workspace(Workspace(root))
        scores.append(score)
        labels.append(root.name)
        print(_report(score, root.name))
    print()
    print(reach_table(scores, labels))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main(sys.argv[1:]))
