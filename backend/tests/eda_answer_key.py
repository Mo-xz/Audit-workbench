"""The procurement sample's answer key, scored against a workspace's analyses.

The key is the Class 1 table (P-01 to P-14) of
``docs/sample-procurement/FACILITATOR_GUIDE.md``: the exceptions visible in the
pack's six workbooks. Earlier run-by-run tables were rebuilt by hand three times
and were wrong once. This module is the rebuild, once, in code: an answer key of
*records*, a scorer over a workspace's saved analyses, and a rendering of the
same reach table.

It scores the exploratory analyses only. Whether a run carried an item on into
a finding and the report is the guide's own scoring, made against the findings;
the guide's document-only and judgement items (``OUT_OF_SCOPE``) are never
reachable by an analysis at all. It replaces an earlier A01-A33 key, written for
a larger edition of the same data whose records this pack does not hold.

Three rules govern scoring and are intentionally enforced here rather than left
to documentation:

* **Match the records, never the spec or the title.** A key item names the
  records the guide names, and an analysis reaches it when the rows it flagged
  include every one of them. An earlier version matched library test ids and
  column sets instead, and it was wrong in both directions at once: a
  completeness check over three approval dates flagged exactly P-08's three
  invoices and did not count, and no python analysis could count at all, so
  P-11 (a unit price derived within each item) was unscoreable by
  construction. The flagged rows are the conclusion; the spec is only how it
  was reached.
* **A saturated hit is not a hit.** A result flagging its whole population
  establishes nothing about any row in it, and the application already says so
  — so the scorer asks ``analysis_results.uninformative_reason`` rather than
  keeping a second opinion.
* **A broad hit is not a hit.** A result that flags the item's records among
  many others has not isolated them: a check that flags forty invoices
  including P-07's three is not the over-billing test. Past
  ``BROAD_FACTOR`` times the item's own record count, plus ``BROAD_SLACK``, a
  capture is reported as broad and not counted.

Records are read from the evidence sidecar each execution writes
(``analysis_results.read_exception_evidence``), which holds up to
``EXCEPTION_ROWS`` flagged rows stamped with the result they belong to. A record
is matched in the column the reading names, so the population still decides: a
blank ``PO_NUMBER`` flagged on requisitions names requisitions, and the same
check over the PO table names none. Where an item's population matters its
reading also names a ``root``, the base table the flagged rows must be rows of.

Run it directly to score a workspace::

    uv run --no-project python backend/tests/eda_answer_key.py Workspaces/Users/local/Workspaces/procurement
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

if __name__ == "__main__":  # pragma: no cover - direct-invocation convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import analysis_results
from app.agent import joins as join_diagnostics
from app.workspaces import Workspace

#: How many rows a capture may flag, relative to the item's own records, before
#: it stops counting as having isolated them.
BROAD_FACTOR = 3
BROAD_SLACK = 2


@dataclass(frozen=True)
class Reading:
    """One way of naming an item's records: the column and the ids it holds.

    ``root`` is the base table the flagged rows must be rows *of*, where the
    population is what distinguishes the item. A joined frame carries every
    chain's ids side by side, so a requisition's limit breach flags a row that
    also holds that requisition's PO number — and without a root, the limit
    check on REQ2024127 scored as the unit-price item on PO2024127.
    """

    column: str
    ids: frozenset[str]
    root: str | None = None


@dataclass(frozen=True)
class KeyItem:
    """One answer-key item and the records that state it.

    ``readings`` are alternatives: an analysis reaches the item when it flags
    every record of any one of them. P-05 is the case that needs more than one,
    because the vendor master names the two vendors and the chain names the
    invoices paid to them, and either is the finding.
    """

    id: str
    label: str
    readings: tuple[Reading, ...]


def _records(column: str, *ids: str, root: str | None = None) -> Reading:
    return Reading(column, frozenset(ids), root)


# The key. Item text and records are the Class 1 table of
# ``docs/sample-procurement/FACILITATOR_GUIDE.md``; ``test_the_key_is_the_
# facilitator_guide`` holds the two together.
ANSWER_KEY: tuple[KeyItem, ...] = (
    KeyItem(
        "P-01",
        "requisition verified by its own requester",
        (_records("REQUISITION_ID", "REQ2024108", "REQ2024120", "REQ2024134", "REQ2024149", root="requisitions"),),
    ),
    KeyItem(
        "P-02",
        "requisition approved above the approver's limit",
        (_records("REQUISITION_ID", "REQ2024112", "REQ2024127", "REQ2024145", root="requisitions"),),
    ),
    KeyItem(
        "P-03",
        "procurement approval not recorded",
        (_records("REQUISITION_ID", "REQ2024116", "REQ2024130", "REQ2024152", root="requisitions"),),
    ),
    KeyItem(
        "P-04",
        "approved requisition neither ordered nor withdrawn",
        (_records("REQUISITION_ID", "REQ2024124", "REQ2024138", "REQ2024153", root="requisitions"),),
    ),
    KeyItem(
        "P-05",
        "vendor not Active, yet ordered from and paid",
        (
            _records("INVOICE_ID", "INV2024126", "INV2024150"),
            _records("PO_NUMBER", "PO2024126", "PO2024150"),
            _records("REQUISITION_ID", "REQ2024126", "REQ2024150"),
            _records("VENDOR_ID", "V1010", "V1017"),
        ),
    ),
    KeyItem(
        "P-06",
        "invoice settled with no goods receipt reference",
        (_records("INVOICE_ID", "INV2024110", "INV2024132", "INV2024147", root="invoice_data"),),
    ),
    KeyItem(
        "P-07",
        "invoice amount above the PO total",
        (_records("INVOICE_ID", "INV2024106", "INV2024140", "INV2024122"),),
    ),
    KeyItem(
        "P-08",
        "invoice paid with no approval recorded",
        (_records("INVOICE_ID", "INV2024104", "INV2024131", "INV2024154", root="invoice_data"),),
    ),
    KeyItem(
        "P-09",
        "invoice approved above the approver's limit",
        (_records("INVOICE_ID", "INV2024127", "INV2024140", root="invoice_data"),),
    ),
    KeyItem(
        "P-10",
        "payment released before the goods receipt",
        (_records("INVOICE_ID", "INV2024114", "INV2024129", "INV2024143"),),
    ),
    KeyItem(
        "P-11",
        "unit price far above every other order for the same item",
        (_records("PO_NUMBER", "PO2024127", root="po_data"),),
    ),
    KeyItem(
        "P-12",
        "invoice dated before its PO",
        (_records("INVOICE_ID", "INV2024004"),),
    ),
    KeyItem(
        "P-13",
        "invoice received before its own invoice date",
        (_records("INVOICE_ID", "INV2024118", "INV2024136"),),
    ),
    KeyItem(
        "P-14",
        "invoice dated or received before the goods receipt",
        # Read on the received date INV2024136 also qualifies, by one day. The
        # four are common to both readings, so flagging them is the finding.
        (_records("INVOICE_ID", "INV2024004", "INV2024114", "INV2024129", "INV2024143"),),
    ),
)

# Document-only and judgement items (Classes 2 and 3 of the guide), outside the
# EDA's scope entirely: no table carries them.
OUT_OF_SCOPE = ("D-01", "D-02", "D-03", "D-04", "D-05", "J-01", "J-02", "J-03")

#: Reads one analysis' flagged rows as ``{"columns": [...], "rows": [[...]]}``,
#: or ``None`` where it flagged nothing or kept no evidence.
EvidenceReader = Callable[[Mapping[str, object]], Mapping[str, object] | None]


@dataclass(frozen=True)
class Hit:
    """One saved analysis whose flagged rows include an item's records."""

    analysis_id: str
    table: str
    kind: str
    found: int
    expected: int
    flagged: int
    denominator: int | None

    @property
    def captured(self) -> bool:
        return self.found == self.expected

    @property
    def broad(self) -> bool:
        return self.flagged > BROAD_FACTOR * self.expected + BROAD_SLACK

    @property
    def fraction(self) -> str:
        population = f" of {self.denominator}" if self.denominator else ""
        return f"{self.found}/{self.expected} ({self.flagged}{population} flagged)"


@dataclass(frozen=True)
class ItemScore:
    item: KeyItem
    hits: tuple[Hit, ...] = ()
    #: Analyses whose flagged rows hold the item's records but establish
    #: nothing, and why.
    rejected: tuple[tuple[str, str], ...] = ()

    @property
    def reached(self) -> bool:
        return any(hit.captured and not hit.broad for hit in self.hits)

    @property
    def best(self) -> Hit | None:
        ranked = sorted(
            self.hits,
            key=lambda hit: (not (hit.captured and not hit.broad), -hit.found, hit.flagged, hit.analysis_id),
        )
        return ranked[0] if ranked else None

    @property
    def status(self) -> str:
        if self.reached:
            return "captured"
        best = self.best
        if best is not None and best.captured:
            return "broad"
        if best is not None:
            return "partial"
        if self.rejected:
            return "saturated"
        return "absent"


@dataclass(frozen=True)
class Score:
    workspace_id: str
    run_id: str | None
    items: tuple[ItemScore, ...]
    analyses: int

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


def _column_values(evidence: Mapping[str, object], column: str) -> set[str]:
    """Every value the flagged rows hold in ``column``, as text."""
    frame = evidence.get("frame") if isinstance(evidence.get("frame"), Mapping) else evidence
    columns = [str(name) for name in frame.get("columns") or []]
    if column not in columns:
        return set()
    index = columns.index(column)
    return {
        str(row[index]).strip()
        for row in frame.get("rows") or []
        if isinstance(row, (list, tuple)) and index < len(row) and row[index] is not None
    }


def _flagged_count(evidence: Mapping[str, object]) -> int:
    frame = evidence.get("frame") if isinstance(evidence.get("frame"), Mapping) else evidence
    return len(frame.get("rows") or [])


def score_workspace(
    workspace: Workspace,
    *,
    run_id: str | None = None,
    evidence: EvidenceReader | None = None,
) -> Score:
    """Score every saved analysis in a workspace against the answer key.

    ``run_id`` restricts scoring to one agent run, which is what makes two runs
    in the same workspace comparable. With it absent every saved analysis
    counts, including any the auditor wrote — the same basis used for the pinned
    measurement, since the measured runs are unattended and author everything
    they hold.

    ``evidence`` reads an analysis' flagged rows; the default reads the sidecar
    its last execution wrote, and returns nothing for a result it no longer
    belongs to.
    """
    read = evidence or (lambda analysis: analysis_results.read_exception_evidence(workspace, analysis))
    analyses = [
        item
        for item in workspace.analyses
        if run_id is None or str(item.get("agent_run_id") or "") == run_id
    ]
    flagged: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for analysis in analyses:
        result = analysis.get("last_result")
        result = result if isinstance(result, Mapping) else {}
        if not int(result.get("exception_count") or 0):
            # A clean result is a test that ran and found nothing. It is a real
            # answer about the data and it names no record.
            continue
        rows = read(analysis)
        if rows:
            flagged.append((analysis, rows))

    scored: list[ItemScore] = []
    for key in ANSWER_KEY:
        hits: list[Hit] = []
        rejected: list[tuple[str, str]] = []
        for analysis, rows in flagged:
            result = analysis.get("last_result")
            result = result if isinstance(result, Mapping) else {}
            exceptions = int(result.get("exception_count") or 0)
            tested = result.get("tested")
            population = result.get("population")
            denominator = next(
                (int(value) for value in (tested, population) if isinstance(value, int) and value),
                None,
            )
            root = _analysis_root(workspace, str(analysis.get("table") or ""))
            best: Hit | None = None
            for reading in key.readings:
                if reading.root is not None and reading.root != root:
                    continue
                found = len(reading.ids & _column_values(rows, reading.column))
                if not found:
                    continue
                candidate = Hit(
                    str(analysis.get("id") or ""),
                    str(analysis.get("table") or ""),
                    str(analysis.get("kind") or ""),
                    found,
                    len(reading.ids),
                    max(exceptions, _flagged_count(rows)),
                    denominator,
                )
                if best is None or (candidate.found / candidate.expected) > (best.found / best.expected):
                    best = candidate
            if best is None:
                continue
            reason = analysis_results.uninformative_reason(
                analysis,
                exception_count=exceptions,
                denominator=denominator,
                rate=(exceptions / denominator) if denominator else None,
            )
            if reason:
                rejected.append((best.analysis_id, reason))
                continue
            hits.append(best)
        scored.append(ItemScore(key, tuple(hits), tuple(rejected)))
    return Score(
        workspace_id=str(workspace.id),
        run_id=run_id,
        items=tuple(scored),
        analyses=len(analyses),
    )


_CELL = {"saturated": "*sat.*", "broad": "*broad*", "partial": "*partial*", "absent": "—"}


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
                cells.append(entry.best.fraction)
            elif entry.status == "partial":
                cells.append(f"*partial {entry.best.found}/{entry.best.expected}*")
            else:
                cells.append(_CELL[entry.status])
        lines.append(f"| {key.item.id} {key.item.label} | " + " | ".join(cells) + " |")
    totals = " | ".join(f"**{len(score.reached)}**" for score in scores)
    lines.append(f"| **Reached** | {totals} |")
    return "\n".join(lines)


def _report(score: Score, label: str) -> str:
    lines = [
        f"{label}: {len(score.reached)} of {score.addressable} items "
        f"from {score.analyses} analyses"
    ]
    for status in ("partial", "broad", "saturated", "absent"):
        ids = [item.item.id for item in score.items if item.status == status]
        if ids:
            lines.append(f"  {status}: " + ", ".join(ids))
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
