"""Library tests that describe a population rather than hunt one exception.

The exploratory memo an auditor writes before designing tests is mostly made of
these: where the value sits, what the process looks like step by step, who
holds which role, which figures behave like a price list. Each is a Polars
computation over one frame — a base table, or a chain of tables aligned by an
analysis input recipe — and each returns an aggregate summary small enough to
read, with the rows that break the pattern as its detail where there are any.

They are registered beside the exception tests in ``analytics.ANALYTICS`` and
run through the same contract. The descriptive ones are excluded from model
proposals by the analysis workflow and are instead written by the profile
sweep (``agent.data_map``); the screening ones may be proposed like any other.
"""

from __future__ import annotations

import math
from itertools import combinations

import polars as pl

from .analytics import (
    SIGNAL_DESCRIPTIVE,
    SIGNAL_EXCEPTION,
    SIGNAL_SCREENING,
    AnalyticsResult,
    _date_expr,
    _stat,
)
from .explore import QueryError
from .text import counted, verb

# Groups past this many fold into one "Other" row, so a breakdown of a
# near-unique column stays a breakdown and does not restate the rows.
MAX_GROUPS = 15
MAX_CROSSTAB_COLUMNS = 12
# Two roles that coincide on this share of rows or less are separate roles, and
# the rows where they coincide are the exception. Above it, the overlap is how
# the process is organised and is described rather than flagged.
RARE_OVERLAP_RATE = 0.10
# Share of a week's days that fall on Saturday or Sunday.
RANDOM_WEEKEND_SHARE = 2 / 7
NO_LIMIT = 1e11


def _require(df: pl.DataFrame, *columns: str) -> None:
    for column in columns:
        if column not in df.columns:
            raise QueryError(f"Unknown column '{column}'.")


def _columns(params: dict, name: str = "columns", minimum: int = 1) -> list[str]:
    columns = [str(c) for c in (params.get(name) or []) if str(c or "").strip()]
    if len(columns) < minimum:
        raise QueryError(f"Pick at least {minimum} column{'s' if minimum > 1 else ''}.")
    return columns


def _blank(column: str, dtype: pl.DataType) -> pl.Expr:
    expr = pl.col(column).is_null()
    if dtype == pl.String:
        expr = expr | (pl.col(column).str.strip_chars() == "")
    return expr


def _number(df: pl.DataFrame, column: str) -> pl.Expr:
    _require(df, column)
    return pl.col(column).cast(pl.Float64, strict=False)


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


# ------------------------------------------------------------------ breakdown
def breakdown(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    dimension = str(params.get("dimension") or "")
    measure = str(params.get("measure") or "")
    party = str(params.get("party") or "")
    _require(df, dimension, *(c for c in (measure, party) if c))
    aggregations = [pl.len().alias("rows")]
    if measure:
        aggregations.append(_number(df, measure).sum().round(2).alias("value"))
    if party:
        aggregations.append(pl.col(party).n_unique().alias("people"))
    grouped = df.group_by(pl.col(dimension).cast(pl.String).fill_null("(blank)")).agg(aggregations)
    order = "value" if measure else "rows"
    grouped = grouped.sort([order, dimension], descending=[True, False])
    if grouped.height > MAX_GROUPS:
        head = grouped.head(MAX_GROUPS - 1)
        rest = grouped.slice(MAX_GROUPS - 1)
        other = {dimension: f"Other ({rest.height} groups)", "rows": int(rest["rows"].sum())}
        if measure:
            other["value"] = float(rest["value"].sum())
        if party:
            other["people"] = None
        grouped = pl.concat([head, pl.DataFrame([other], schema=head.schema)], how="vertical_relaxed")
    total_rows = df.height
    total_value = float(grouped["value"].sum()) if measure else 0.0
    grouped = grouped.with_columns(
        (100.0 * pl.col(order) / (total_value if measure else total_rows)).round(1).alias("share_pct")
    )
    shares = grouped["share_pct"].to_list()
    stats = [
        _stat("Groups", df.select(pl.col(dimension).n_unique()).item()),
        _stat("Largest share", f"{shares[0]}%") if shares else _stat("Largest share", "—"),
        _stat("Top three", f"{round(sum(shares[:3]), 1)}%"),
    ]
    if measure:
        stats.append(_stat("Total value", total_value))
    top = grouped.row(0, named=True) if grouped.height else None
    text = (
        f"{top[dimension]} holds {top['share_pct']}% of {'the value' if measure else 'the rows'}"
        if top else "No rows to break down"
    )
    return AnalyticsResult(
        title=f"{measure or 'Rows'} by {dimension}",
        verdict="info",
        verdict_text=text,
        stats=stats,
        summary=grouped,
        tested=total_rows,
        viz={"type": "hbar", "x": dimension, "y": [order], "label": ["share_pct"]},
    )


# ------------------------------------------------------------------- crosstab
def crosstab(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    rows = str(params.get("rows") or "")
    columns = str(params.get("columns") or "")
    _require(df, rows, columns)
    frame = df.select(
        pl.col(rows).cast(pl.String).fill_null("(blank)").alias("r"),
        pl.col(columns).cast(pl.String).fill_null("(blank)").alias("c"),
    )
    top_columns = (
        frame.group_by("c").len().sort(["len", "c"], descending=[True, False])
        .head(MAX_CROSSTAB_COLUMNS)["c"].to_list()
    )
    folded = frame.with_columns(
        pl.when(pl.col("c").is_in(top_columns)).then(pl.col("c")).otherwise(pl.lit("Other")).alias("c")
    )
    counts = folded.group_by("r", "c").len()
    table = counts.pivot(on="c", index="r", values="len").fill_null(0)
    present = [c for c in [*top_columns, "Other"] if c in table.columns]
    table = table.select("r", *present).with_columns(
        pl.sum_horizontal(present).alias("total")
    ).sort(["total", "r"], descending=[True, False]).rename({"r": rows})
    # Cramér's V over the unfolded table: how far one category predicts the
    # other. Near 1 the two columns restate each other; near 0 knowing one says
    # nothing about the other.
    n = frame.height
    full = frame.group_by("r", "c").len()
    row_totals = frame.group_by("r").len().rename({"len": "nr"})
    col_totals = frame.group_by("c").len().rename({"len": "nc"})
    expected = row_totals.join(col_totals, how="cross").with_columns(
        (pl.col("nr") * pl.col("nc") / n).alias("e")
    ).join(full.rename({"len": "o"}), on=["r", "c"], how="left").with_columns(pl.col("o").fill_null(0))
    chi = float(expected.select(((pl.col("o") - pl.col("e")) ** 2 / pl.col("e")).sum()).item()) if n else 0.0
    k = min(row_totals.height, col_totals.height) - 1
    cramers = round(math.sqrt(chi / (n * k)), 3) if n and k > 0 else None
    return AnalyticsResult(
        title=f"{rows} by {columns}",
        verdict="info",
        verdict_text=(
            f"{counted(row_totals.height, 'value')} of {rows} against "
            f"{counted(col_totals.height, 'value')} of {columns}"
        ),
        stats=[
            _stat("Rows", n),
            _stat("Association (Cramér's V)", cramers if cramers is not None else "—"),
        ],
        summary=table,
        tested=n,
        viz={"type": "heatmap", "x": rows, "exclude": ["total"]},
    )


# ---------------------------------------------------------------- value bands
def _round_edges(low: float, high: float) -> list[float]:
    """Band edges on round numbers (1, 5, 10, 50 …) spanning the values."""
    edges = []
    if high <= 0:
        return edges
    start = math.floor(math.log10(max(low, 1.0)))
    for power in range(start, math.ceil(math.log10(high)) + 1):
        for step in (1, 5):
            edge = step * 10 ** power
            if low < edge < high:
                edges.append(float(edge))
    while len(edges) > 6:
        edges = edges[::2]
    return edges


def _label(value: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= size:
            text = f"{value / size:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{value:,.0f}"


def value_bands(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    column = str(params.get("column") or "")
    values = df.select(_number(df, column).alias("v")).drop_nulls()
    if values.is_empty():
        raise QueryError(f"'{column}' has no numeric values.")
    low, high = float(values["v"].min()), float(values["v"].max())
    edges = _round_edges(low, high)
    bounds = [-math.inf, *edges, math.inf]
    labels = []
    for lower, upper in zip(bounds, bounds[1:]):
        if lower == -math.inf:
            labels.append(f"Up to {_label(upper)}" if upper != math.inf else "All")
        elif upper == math.inf:
            labels.append(f"Over {_label(lower)}")
        else:
            labels.append(f"{_label(lower)} to {_label(upper)}")
    banded = values.with_columns(
        pl.col("v").cut(edges, labels=labels, left_closed=False).alias("band")
    ) if edges else values.with_columns(pl.lit(labels[0]).alias("band"))
    total_rows, total_value = values.height, float(values["v"].sum())
    summary = (
        banded.group_by("band").agg(pl.len().alias("rows"), pl.col("v").sum().round(2).alias("value"))
        .with_columns(pl.col("band").cast(pl.String))
    )
    summary = pl.DataFrame({"band": labels}).join(summary, on="band", how="left").fill_null(0).with_columns(
        (100.0 * pl.col("rows") / total_rows).round(1).alias("rows_pct"),
        (100.0 * pl.col("value") / total_value).round(1).alias("value_pct") if total_value else pl.lit(0.0).alias("value_pct"),
    )
    ordered = values["v"].sort(descending=True)
    cumulative = (ordered.cum_sum() / total_value).to_list() if total_value else []
    to_80 = next((i + 1 for i, share in enumerate(cumulative) if share >= 0.8), total_rows)
    return AnalyticsResult(
        title=f"{column} by size band",
        verdict="info",
        verdict_text=f"{counted(to_80, 'row')} of {total_rows} carry 80% of the value",
        stats=[
            _stat("Rows", total_rows),
            _stat("Rows to 80% of value", to_80),
            _stat("Median", float(values["v"].median())),
            _stat("Largest", high),
        ],
        summary=summary,
        tested=total_rows,
        viz={"type": "share", "x": "band", "y": ["rows_pct", "value_pct"]},
    )


# ------------------------------------------------------------ step durations
def step_durations(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params, minimum=2)
    dated = df.with_columns([_date_expr(df, c).alias(f"__d{i}") for i, c in enumerate(columns)])
    rows = []
    breaks = []
    for i, (a, b) in enumerate(zip(columns, columns[1:])):
        days = (pl.col(f"__d{i + 1}") - pl.col(f"__d{i}")).dt.total_days()
        series = dated.select(days.alias("d"))["d"].drop_nulls()
        if series.is_empty():
            rows.append({"step": f"{a} → {b}", "records": 0, "min": None, "p25": None, "median": None,
                         "p75": None, "max": None, "before_previous": 0})
            continue
        rows.append({
            "step": f"{a} → {b}",
            "records": series.len(),
            "min": int(series.min()),
            "p25": float(series.quantile(0.25, "nearest")),
            "median": float(series.median()),
            "p75": float(series.quantile(0.75, "nearest")),
            "max": int(series.max()),
            "before_previous": int((series < 0).sum()),
        })
        breaks.append(pl.when(days < 0).then(pl.lit(f"{b} before {a}")))
    summary = pl.DataFrame(rows)
    flagged = dated.with_columns(
        pl.concat_str(breaks, separator="; ", ignore_nulls=True).alias("out_of_order")
    ).filter(pl.col("out_of_order").is_not_null() & (pl.col("out_of_order") != ""))
    flagged = flagged.drop([c for c in flagged.columns if c.startswith("__d")])
    first, last = columns[0], columns[-1]
    end_to_end = dated.select((pl.col(f"__d{len(columns) - 1}") - pl.col("__d0")).dt.total_days().alias("d"))["d"].drop_nulls()
    tested = dated.filter(pl.sum_horizontal([pl.col(f"__d{i}").is_not_null() for i in range(len(columns))]) >= 2).height
    stats = [_stat("Steps", len(columns) - 1), _stat("Rows out of order", flagged.height)]
    if not end_to_end.is_empty():
        stats.append(_stat(f"Median days {first} to {last}", float(end_to_end.median())))
    return AnalyticsResult(
        title=f"Days between {first} and {last}, step by step",
        verdict="warn" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'row')} {verb(flagged.height, 'has', 'have')} a step before the one it should follow"
            if flagged.height else "Every step follows the one before it"
        ),
        stats=stats,
        summary=summary,
        detail=flagged if flagged.height else None,
        tested=tested,
        viz={"type": "range", "x": "step", "y": ["min", "p25", "median", "p75", "max"],
             "flag": "before_previous"},
    )


# ------------------------------------------------------------- skipped steps
def skipped_steps(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params, minimum=2)
    _require(df, *columns)
    blanks = [_blank(c, df.schema[c]) for c in columns]
    later = [
        pl.any_horizontal([~blank for blank in blanks[i + 1:]]) if i + 1 < len(blanks) else pl.lit(False)
        for i in range(len(blanks))
    ]
    reasons = [pl.when(blanks[i] & later[i]).then(pl.lit(columns[i])) for i in range(len(columns))]
    flagged = df.with_columns(
        pl.concat_str(reasons, separator=", ", ignore_nulls=True).alias("skipped")
    ).filter(pl.col("skipped").is_not_null() & (pl.col("skipped") != ""))
    by_column = [
        {"column": c, "blank_with_later_steps": int(df.select((blanks[i] & later[i]).sum()).item())}
        for i, c in enumerate(columns)
    ]
    return AnalyticsResult(
        title="Steps left blank while a later step happened",
        verdict="fail" if flagged.height else "ok",
        verdict_text=(
            f"{counted(flagged.height, 'row')} skipped a step and carried on"
            if flagged.height else "No row skipped a step it later went past"
        ),
        stats=[_stat("Rows", df.height), _stat("Rows with a skipped step", flagged.height)],
        summary=pl.DataFrame(by_column),
        detail=flagged if flagged.height else None,
        tested=df.height,
        viz={"type": "hbar", "x": "column", "y": ["blank_with_later_steps"], "omit_zero": True},
    )


# ---------------------------------------------------------- calendar profile
def calendar_profile(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params)
    rows = []
    total = weekend_total = 0
    for column in columns:
        dates = df.select(_date_expr(df, column).alias("d"))["d"].drop_nulls()
        if dates.is_empty():
            continue
        weekend = int((dates.dt.weekday() >= 6).sum())
        month_end = int((dates.dt.month_end() - dates).dt.total_days().le(2).sum())
        rows.append({
            "column": column,
            "dated": dates.len(),
            "weekend": weekend,
            "weekend_pct": _pct(weekend, dates.len()),
            "month_end_pct": _pct(month_end, dates.len()),
        })
        total += dates.len()
        weekend_total += weekend
    if not rows:
        raise QueryError("None of the chosen columns holds a date.")
    share = weekend_total / total
    keyed = share >= 0.6 * RANDOM_WEEKEND_SHARE
    return AnalyticsResult(
        title="Weekend and month-end share of each date",
        verdict="info",
        verdict_text=(
            f"{_pct(weekend_total, total)}% of dates fall on a weekend, against "
            f"{_pct(RANDOM_WEEKEND_SHARE, 1)}% for dates that ignore the week"
            + ("" if keyed else "; the dates follow a working week")
        ),
        stats=[
            _stat("Dates", total),
            _stat("On a weekend", f"{_pct(weekend_total, total)}%"),
            _stat("If random", f"{_pct(RANDOM_WEEKEND_SHARE, 1)}%"),
        ],
        summary=pl.DataFrame(rows),
        tested=total,
        viz={"type": "hbar", "x": "column", "y": ["weekend_pct"], "unit": "%",
             "reference": {"value": round(100 * RANDOM_WEEKEND_SHARE, 1),
                           "label": f"{round(100 * RANDOM_WEEKEND_SHARE, 1)}%: dates at random"}},
    )


# ----------------------------------------------------------------- role matrix
def role_matrix(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params)
    _require(df, *columns)
    parts = [
        df.select(pl.col(c).cast(pl.String).alias("person")).drop_nulls()
        .group_by("person").len().rename({"len": c})
        for c in columns
    ]
    matrix = parts[0]
    for part in parts[1:]:
        matrix = matrix.join(part, on="person", how="full", coalesce=True)
    matrix = matrix.fill_null(0).with_columns(pl.sum_horizontal(columns).alias("total"))
    # Ordered by the first role each person holds, then by volume, so the
    # matrix reads as the process does: who raises, who checks, who approves.
    first_role = pl.coalesce([pl.when(pl.col(c) > 0).then(pl.lit(i)) for i, c in enumerate(columns)])
    matrix = matrix.with_columns(first_role.alias("__first")).sort(
        ["__first", "total", "person"], descending=[False, True, False]
    ).drop("__first")
    holding_two = matrix.filter(pl.sum_horizontal([(pl.col(c) > 0).cast(pl.Int32) for c in columns]) >= 2).height
    return AnalyticsResult(
        title="Who acts in each role",
        verdict="info",
        verdict_text=(
            f"{counted(matrix.height, 'person', 'people')} across {counted(len(columns), 'role')}; "
            f"{holding_two} hold more than one"
        ),
        stats=[_stat("People", matrix.height), _stat("Roles", len(columns)), _stat("In two or more roles", holding_two)],
        summary=matrix,
        tested=df.height,
        viz={"type": "heatmap", "x": "person", "exclude": ["total"]},
    )


def role_overlap(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params, minimum=2)
    _require(df, *columns)
    rows = []
    rare = []
    for a, b in combinations(columns, 2):
        both = pl.col(a).is_not_null() & pl.col(b).is_not_null()
        same_expr = both & (pl.col(a).cast(pl.String) == pl.col(b).cast(pl.String))
        of = int(df.select(both.sum()).item())
        same = int(df.select(same_expr.sum()).item())
        rate = same / of if of else 0.0
        rows.append({"role": a, "other_role": b, "same_person": same, "of": of, "rate_pct": _pct(same, of)})
        if same and rate <= RARE_OVERLAP_RATE:
            rare.append(pl.when(same_expr).then(pl.lit(f"{a} = {b}")))
    summary = pl.DataFrame(rows).sort("rate_pct", descending=True)
    flagged = (
        df.with_columns(pl.concat_str(rare, separator="; ", ignore_nulls=True).alias("same_person_in"))
        .filter(pl.col("same_person_in").is_not_null() & (pl.col("same_person_in") != ""))
        if rare else df.head(0)
    )
    patterns = summary.filter(pl.col("rate_pct") > 100 * RARE_OVERLAP_RATE).height
    return AnalyticsResult(
        title="The same person in two roles",
        verdict="warn" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'row')} where roles that are almost always held by "
            "different people were held by one"
            if flagged.height else "No role pair coincides only occasionally"
        ),
        stats=[
            _stat("Role pairs", len(rows)),
            _stat("Pairs usually the same person", patterns),
            _stat("Rows flagged", flagged.height),
        ],
        summary=summary,
        detail=flagged if flagged.height else None,
        tested=df.height,
        viz={"type": "heatmap", "row": "role", "x": "other_role", "y": ["rate_pct"], "unit": "%"},
    )


# ---------------------------------------------------------- chain reconciliation
def chain_reconciliation(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params, minimum=2)
    _require(df, *columns)
    numbers = df.with_columns([_number(df, c).alias(f"__v{i}") for i, c in enumerate(columns)])
    rows = []
    above = []
    for i, column in enumerate(columns):
        value = pl.col(f"__v{i}")
        entry = {
            "column": column,
            "present": int(numbers.select(value.is_not_null().sum()).item()),
            "total": float(numbers.select(value.sum()).item() or 0.0),
            "equal_to_previous": None, "above_previous": None, "below_previous": None,
            "excess_over_previous": None, "missing_after_previous": None,
        }
        if i:
            prev = pl.col(f"__v{i - 1}")
            both = numbers.filter(prev.is_not_null() & value.is_not_null())
            entry.update(
                equal_to_previous=int(both.select((value == prev).sum()).item()),
                above_previous=int(both.select((value > prev).sum()).item()),
                below_previous=int(both.select((value < prev).sum()).item()),
                excess_over_previous=float(both.select((value - prev).clip(lower_bound=0).sum()).item() or 0.0),
                missing_after_previous=int(numbers.select((prev.is_not_null() & value.is_null()).sum()).item()),
            )
            above.append(pl.when(value > prev).then(pl.lit(f"{column} above {columns[i - 1]}")))
        rows.append(entry)
    flagged = numbers.with_columns(
        pl.concat_str(above, separator="; ", ignore_nulls=True).alias("above_previous")
    ).filter(pl.col("above_previous").is_not_null() & (pl.col("above_previous") != ""))
    flagged = flagged.drop([c for c in flagged.columns if c.startswith("__v")])
    summary = pl.DataFrame(rows)
    return AnalyticsResult(
        title="Value carried through each step of the chain",
        verdict="warn" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'row')} {verb(flagged.height, 'exceeds', 'exceed')} the value of the step before"
            if flagged.height else "No step exceeds the value of the step before it"
        ),
        stats=[_stat(f"{c} total", r["total"]) for c, r in zip(columns, rows)][:4],
        summary=summary,
        detail=flagged if flagged.height else None,
        tested=df.height,
        viz={"type": "bridge", "x": "column", "y": ["total"]},
    )


# ------------------------------------------------------------ ratio in a group
def ratio_consistency(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    numerator = str(params.get("numerator") or "")
    denominator = str(params.get("denominator") or "")
    group = str(params.get("group") or "")
    factor = float(params.get("factor") or 3)
    _require(df, numerator, denominator, group)
    ratio = (_number(df, numerator) / _number(df, denominator).replace(0, None)).alias("ratio")
    framed = df.with_columns(ratio).with_columns(
        pl.col("ratio").median().over(group).alias("group_median"),
        pl.len().over(group).alias("group_rows"),
    )
    summary = (
        framed.filter(pl.col("ratio").is_not_null())
        .group_by(group).agg(
            pl.len().alias("rows"),
            pl.col("ratio").n_unique().alias("distinct_ratios"),
            pl.col("ratio").median().round(4).alias("median_ratio"),
            pl.col("ratio").min().round(4).alias("min_ratio"),
            pl.col("ratio").max().round(4).alias("max_ratio"),
        ).sort(["rows", group], descending=[True, False])
    )
    flagged = framed.filter(
        (pl.col("group_rows") >= 2)
        & ((pl.col("ratio") > factor * pl.col("group_median")) | (pl.col("ratio") * factor < pl.col("group_median")))
    ).drop("group_rows")
    repeated = summary.filter(pl.col("rows") >= 2)
    single = repeated.filter(pl.col("distinct_ratios") == 1).height
    return AnalyticsResult(
        title=f"{numerator} per {denominator}, within each {group}",
        verdict="warn" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'row')} more than {factor:g} times from the median of {group}"
            if flagged.height else f"Every {group} keeps within {factor:g} times its median"
        ),
        stats=[
            _stat("Groups with two or more rows", repeated.height),
            _stat("Of which one single value", single),
            _stat("Rows far from their group", flagged.height),
        ],
        summary=summary,
        detail=flagged if flagged.height else None,
        tested=int(framed.select(pl.col("ratio").is_not_null().sum()).item()),
        viz={"type": "strip", "x": group, "y": ["min_ratio", "median_ratio", "max_ratio"], "log": True},
    )


# ---------------------------------------------------------- identifier series
def _serial(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String).str.strip_chars()


def id_series(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    columns = _columns(params, minimum=2)
    _require(df, *columns)
    rows = []
    off = []
    for a, b in zip(columns, columns[1:]):
        both = df.filter(pl.col(a).is_not_null() & pl.col(b).is_not_null())
        number_a = _serial(a).str.extract(r"(\d+)\D*$")
        number_b = _serial(b).str.extract(r"(\d+)\D*$")
        # A child identifier written as its parent's with a suffix (EXP-001-L2)
        # belongs to the parent; reading only trailing digits would call every
        # line of a claim off-series.
        nested = _serial(b).str.starts_with(_serial(a)) | _serial(a).str.starts_with(_serial(b))
        same = (number_a == number_b) | nested
        matched = int(both.select(same.sum()).item())
        rows.append({"from": a, "to": b, "same_number": matched, "of": both.height,
                     "share_pct": _pct(matched, both.height)})
        if both.height and matched / both.height >= 0.8:
            off.append(pl.when(pl.col(a).is_not_null() & pl.col(b).is_not_null() & ~same)
                       .then(pl.lit(f"{b} not numbered as {a}")))
    flagged = (
        df.with_columns(pl.concat_str(off, separator="; ", ignore_nulls=True).alias("off_series"))
        .filter(pl.col("off_series").is_not_null() & (pl.col("off_series") != ""))
        if off else df.head(0)
    )
    return AnalyticsResult(
        title="Identifiers carried from one step to the next",
        verdict="warn" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'row')} {verb(flagged.height, 'breaks', 'break')} a numbering the rest share"
            if flagged.height else
            ("Every row shares one numbering across the chain" if off else "The identifiers are numbered independently")
        ),
        stats=[_stat(f"{r['from']} → {r['to']}", f"{r['share_pct']}%") for r in rows][:4],
        summary=pl.DataFrame(rows),
        detail=flagged if flagged.height else None,
        tested=df.height,
        viz={"type": "table"},
    )


# ------------------------------------------------------------- authority grid
def authority_grid(df: pl.DataFrame, params: dict) -> AnalyticsResult:
    amount = str(params.get("amount") or "")
    limit = str(params.get("limit") or "")
    signer = str(params.get("signer") or "")
    _require(df, amount, limit, signer)
    framed = df.with_columns(
        _number(df, amount).alias("__amount"), _number(df, limit).alias("__limit"),
        pl.col(signer).cast(pl.String).fill_null("(no signer)").alias("__signer"),
    )
    limits = sorted({float(v) for v in framed["__limit"].drop_nulls().to_list() if v < NO_LIMIT})
    labels = []
    bounds = [-math.inf, *limits, math.inf]
    for lower, upper in zip(bounds, bounds[1:]):
        labels.append(
            f"Up to {_label(upper)}" if lower == -math.inf and upper != math.inf
            else f"Over {_label(lower)}" if upper == math.inf and lower != -math.inf
            else "All" if lower == -math.inf else f"{_label(lower)} to {_label(upper)}"
        )
    banded = framed.with_columns(
        (pl.col("__amount").cut(limits, labels=labels, left_closed=False) if limits else pl.lit("All"))
        .cast(pl.String).alias("band")
    )
    over = (pl.col("__amount") > pl.col("__limit")) & pl.col("__limit").is_not_null()
    grid = (
        banded.group_by("band", "__signer").agg(
            pl.len().alias("approvals"),
            pl.col("__amount").sum().round(2).alias("value"),
            over.sum().alias("over_limit"),
        ).rename({"__signer": signer})
    )
    grid = pl.DataFrame({"band": labels}).join(grid, on="band", how="inner").sort(["band", signer])
    order = {label: i for i, label in enumerate(labels)}
    grid = grid.with_columns(pl.col("band").replace_strict(order, default=99).alias("__o")).sort(["__o", signer]).drop("__o")
    flagged = banded.filter(over).drop("__amount", "__limit", "__signer", "band")
    by_signer = framed.group_by("__signer").agg(pl.col("__amount").sum()).sort("__amount", descending=True)
    total = float(framed["__amount"].sum() or 0.0)
    top = by_signer.row(0) if by_signer.height else ("—", 0.0)
    unsigned = int(framed.select(pl.col(signer).is_null().sum()).item())
    return AnalyticsResult(
        title=f"{amount} by band against who signed",
        verdict="fail" if flagged.height else "info",
        verdict_text=(
            f"{counted(flagged.height, 'approval')} above the signer's limit; {top[0]} signs "
            f"{_pct(top[1], total)}% of the value"
        ),
        stats=[
            _stat("Over the signer's limit", flagged.height),
            _stat("Largest signer's share", f"{_pct(top[1], total)}%"),
            _stat("No signer recorded", unsigned),
        ],
        summary=grid,
        detail=flagged if flagged.height else None,
        tested=framed.filter(pl.col("__limit").is_not_null()).height,
        viz={"type": "heatmap", "row": "band", "x": signer, "y": ["approvals"], "flag": "over_limit"},
    )


def _column(name: str, label: str, **extra) -> dict:
    return {"name": name, "kind": "column", "label": label, **extra}


def _columns_param(label: str) -> dict:
    return {"name": "columns", "kind": "columns", "label": label}


PROFILE_ANALYTICS: dict[str, dict] = {
    "breakdown": {
        "group": "Profile",
        "label": "Breakdown by category",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-chart-bar",
        "description": "Count, value and share for each value of one category, largest first.",
        "params": [
            _column("dimension", "Category column"),
            _column("measure", "Amount column", column_kind="numeric", optional=True),
            _column("party", "Person column (distinct count)", optional=True),
        ],
        "func": breakdown,
    },
    "crosstab": {
        "group": "Profile",
        "label": "Two-way table",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-table",
        "description": "Counts of one category against another, with how far one predicts the other.",
        "params": [_column("rows", "Row category"), _column("columns", "Column category")],
        "func": crosstab,
    },
    "value_bands": {
        "group": "Profile",
        "label": "Value bands",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-sort-amount-down",
        "description": "Rows and value in round-number bands, and how few rows carry most of the value.",
        "params": [_column("column", "Amount column", column_kind="numeric")],
        "func": value_bands,
    },
    "step_durations": {
        "group": "Profile",
        "label": "Step durations",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-clock",
        "description": "Days between consecutive dates of a process, and the rows where a step came before the one it should follow.",
        "params": [_columns_param("Dates, in process order")],
        "func": step_durations,
    },
    "skipped_steps": {
        "group": "Dates & approvals",
        "label": "Skipped steps",
        "signal": SIGNAL_EXCEPTION,
        "icon": "pi pi-step-forward",
        "description": "Rows where a step was left blank and a later step still happened — paid without approval, ordered without sign-off.",
        "params": [_columns_param("Step columns, in process order")],
        "func": skipped_steps,
    },
    "calendar_profile": {
        "group": "Profile",
        "label": "Calendar profile",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-calendar",
        "description": "Weekend and month-end share of each date column, against what dates ignoring the calendar would give.",
        "params": [_columns_param("Date columns")],
        "func": calendar_profile,
    },
    "role_matrix": {
        "group": "Profile",
        "label": "Role matrix",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-users",
        "description": "How many times each person acts in each role column.",
        "params": [_columns_param("Person columns, one per role")],
        "func": role_matrix,
    },
    "role_overlap": {
        "group": "Dates & approvals",
        "label": "Same person in two roles",
        "signal": SIGNAL_SCREENING,
        "icon": "pi pi-user-minus",
        "description": "How often each pair of roles is held by one person; flags the rows where roles almost always held apart coincide.",
        "params": [_columns_param("Person columns, one per role")],
        "func": role_overlap,
    },
    "chain_reconciliation": {
        "group": "Profile",
        "label": "Chain reconciliation",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-arrow-right-arrow-left",
        "description": "The value at each step of a chain against the step before: equal, above, below, and what never reached the next step.",
        "params": [_columns_param("Amount columns, in chain order")],
        "func": chain_reconciliation,
    },
    "ratio_consistency": {
        "group": "Amounts & outliers",
        "label": "Ratio within a group",
        "signal": SIGNAL_SCREENING,
        "icon": "pi pi-percentage",
        "description": "Divides one amount by another (a unit price) and flags rows far from their group's median.",
        "params": [
            _column("numerator", "Amount column", column_kind="numeric"),
            _column("denominator", "Divided by (e.g. quantity)", column_kind="numeric"),
            _column("group", "Within each"),
            {"name": "factor", "kind": "number", "label": "Times the median", "default": 3, "optional": True},
        ],
        "func": ratio_consistency,
    },
    "id_series": {
        "group": "Duplicates & sequences",
        "label": "Identifier series",
        "signal": SIGNAL_SCREENING,
        "icon": "pi pi-sort-numeric-up",
        "description": "Whether identifiers carried along a chain share one numbering, and which rows break it.",
        "params": [_columns_param("Identifier columns, in chain order")],
        "func": id_series,
    },
    "authority_grid": {
        "group": "Profile",
        "label": "Authority grid",
        "signal": SIGNAL_DESCRIPTIVE,
        "icon": "pi pi-sitemap",
        "description": "Amounts banded at the approval limits against who signed, with the approvals above the signer's limit.",
        "params": [
            _column("amount", "Amount column", column_kind="numeric"),
            _column("limit", "Signer's limit column", column_kind="numeric"),
            _column("signer", "Signer column"),
        ],
        "func": authority_grid,
    },
}

#: The tests the profile sweep writes and a model may not propose.
PROFILE_DESCRIPTIVE_IDS = frozenset(
    test_id for test_id, meta in PROFILE_ANALYTICS.items() if meta["signal"] == SIGNAL_DESCRIPTIVE
)
