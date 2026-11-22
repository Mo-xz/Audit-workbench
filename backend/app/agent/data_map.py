"""The data map: what each imported table is, read from the data, with no model.

An analyst's first hour on a new set of tables is spent working out what they
are: which tables hold transactions and which are lists of people and vendors,
which transactions follow from which, the order the dates put the process in,
which columns say *who* did each step, which number is the amount and which is
a limit or a code. Everything else — the profile, the tests, the memo — is
written against those answers. This module computes them from the profiler and
the same join diagnostics ``data.relationships_inferred`` uses, and names no
column of any particular engagement.

It is deliberately conservative about the chain. Only links that cannot
multiply rows join it (each table joined in carries a unique key for the link),
so the chain frame has one row per root record. A table whose rows hang many to
one beneath another — the lines of a claim — is recorded as a *child* of it,
not joined: comparing a line's amount with a claim's total is a units mistake.

``profile_definitions`` turns the map into saved-analysis definitions over the
descriptive and screening tests in ``analytics_profile``. They are written by
``analysis.profiled`` and executed like any other analysis.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from threading import RLock

import polars as pl

from ..analysis_inputs import InputWorkspace, validate_input
from ..workspaces import Workspace, WorkspaceError, join_suffix
from . import joins
from .probes import reference_shaped

MAP_VERSION = 1
#: ``analysis_inputs.MAX_INPUT_JOINS``: a chain longer than this is cut, and the
#: tables left over are reported rather than silently dropped.
MAX_CHAIN_JOINS = 3
#: Lookups are small reference tables, an approval matrix being the type.
MAX_LOOKUP_ROWS = 50
#: Two columns of one table that resolve to the same master row this often are
#: one role written twice (an id and a name), not two roles.
ALIAS_AGREEMENT = 0.95
#: An authority grid is only drawn for a role whose signers the lookup actually
#: covers: a grid with most signers unlimited describes the lookup, not the role.
MIN_AUTHORITY_COVERAGE = 0.5
MAX_CROSSTABS = 2
PROFILE_PREFIX = "profile:"

_GENERIC_TOKENS = frozenset(
    {"date", "dt", "id", "by", "on", "at", "no", "num", "number", "code", "ref", "time", "timestamp", "the", "of"}
)
_LIMIT_TOKENS = frozenset({"limit", "max", "maximum", "ceiling", "threshold", "cap", "delegated", "authority"})
_QUANTITY_TOKENS = frozenset({"qty", "quantity", "units", "count", "pcs", "pieces", "volume"})
_RATE_TOKENS = frozenset({"rate", "pct", "percent", "percentage", "ratio", "price", "tariff", "fx"})
_CODE_TOKENS = frozenset({"account", "code", "gl", "ledger", "year", "month", "no", "num", "number", "id", "ref", "zip", "phone", "cnic"})
_STATUS_TOKENS = frozenset({"status", "state", "decision", "stage", "flag"})
_NAME_TOKENS = frozenset({"name", "title", "description"})

_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = RLock()
_CACHE_SIZE = 16


def _tokens(column: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z]+|\d+", str(column))]


def _stem(token: str) -> str:
    return token[:5]


def _subject(column: str) -> frozenset[str]:
    return frozenset(_stem(t) for t in _tokens(column) if t not in _GENERIC_TOKENS and not t.isdigit())


def _sha(value: object, length: int = 10) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:length]


def _unique(series: pl.Series) -> bool:
    present = series.drop_nulls()
    return present.len() > 0 and present.n_unique() == present.len()


def _median_date(frame: pl.DataFrame, column: str):
    values = frame[column].drop_nulls()
    if values.is_empty():
        return None
    if not values.dtype.is_temporal():
        values = values.cast(pl.String).str.to_date(strict=False).drop_nulls()
    return values.cast(pl.Date).median() if values.len() else None


# --------------------------------------------------------------------------- #
# column typing
# --------------------------------------------------------------------------- #
def _numeric_kind(column: str) -> str:
    tokens = set(_tokens(column))
    if tokens & _LIMIT_TOKENS:
        return "limit"
    if tokens & _QUANTITY_TOKENS:
        return "quantity"
    if tokens & _RATE_TOKENS:
        return "rate"
    if tokens & _CODE_TOKENS:
        return "code"
    return "amount"


def _table_columns(workspace: Workspace, table: str) -> dict:
    profile = workspace.get_profile(table)
    by_name = {str(p["name"]): p for p in profile.get("column_profiles") or []}
    frame = workspace.get_frame(table)
    typed: dict[str, list[str]] = {
        "dates": [], "amounts": [], "limits": [], "quantities": [], "rates": [], "codes": [],
        "dimensions": [], "statuses": [], "keys": [],
    }
    for column in frame.columns:
        p = by_name.get(column) or {}
        kind = str(p.get("inferred_type") or "")
        if _unique(frame[column]) and frame[column].null_count() == 0 and kind != "date":
            typed["keys"].append(column)
        if kind == "date":
            typed["dates"].append(column)
        elif kind == "numeric":
            numeric = _numeric_kind(column)
            if numeric == "amount" and p.get("sum") is None:
                numeric = "code"
            typed[{"amount": "amounts", "limit": "limits", "quantity": "quantities",
                   "rate": "rates", "code": "codes"}[numeric]].append(column)
        elif kind == "categorical":
            distinct = int(p.get("distinct_count") or 0)
            if set(_tokens(column)) & _STATUS_TOKENS or distinct <= 2:
                typed["statuses"].append(column)
            else:
                typed["dimensions"].append(column)
    # The measure is the amount the table adds up to most.
    def _total(column: str) -> float:
        try:
            return abs(float(str(by_name[column].get("sum")).replace(",", "")))
        except (TypeError, ValueError):
            return 0.0
    typed["amounts"].sort(key=lambda c: -_total(c))
    # Reference-shaped key names first, so an id beats an incidental unique text.
    typed["keys"].sort(key=lambda c: (not reference_shaped(c), frame.columns.index(c)))
    return {"rows": frame.height, **typed, "profiles": by_name}


# --------------------------------------------------------------------------- #
# relationships
# --------------------------------------------------------------------------- #
def _edges(workspace: Workspace, tables: Sequence[str]) -> list[dict]:
    """Strong key matches between every ordered pair, with uniqueness facts."""
    frames = {name: workspace.get_frame(name) for name in tables}
    entities = joins.entity_tokens(list(tables))
    key_cache: dict = {}
    found = []
    for left in tables:
        for right in tables:
            if left == right:
                continue
            lf, rf = frames[left], frames[right]
            for lc, rc, _affinity in joins.candidate_keys(lf, rf, right, entities):
                diagnostics = joins.diagnose(lf, rf, lc, rc, key_cache=key_cache)
                if joins.classify(diagnostics) != "strong":
                    continue
                found.append({
                    "left": left, "left_on": lc, "right": right, "right_on": rc,
                    "left_unique": _unique(lf[lc]), "right_unique": _unique(rf[rc]),
                    "left_nulls": int(lf[lc].null_count()),
                })
    return found


# --------------------------------------------------------------------------- #
# the map
# --------------------------------------------------------------------------- #
def build_data_map(workspace: Workspace, tables: Iterable[str] | None = None) -> dict:
    """The data map for ``tables`` (default: every imported table). Cached."""
    names = tuple(sorted(tables if tables is not None else workspace.table_names()))
    names = tuple(n for n in names if n in set(workspace.table_names()))
    key = (str(workspace.root), tuple((n, workspace.content_signature(n)) for n in names))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return json.loads(_CACHE[key])
    result = _build(workspace, names)
    with _CACHE_LOCK:
        _CACHE[key] = json.dumps(result, default=str)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


def _build(workspace: Workspace, names: tuple[str, ...]) -> dict:
    info = {name: _table_columns(workspace, name) for name in names}
    frames = {name: workspace.get_frame(name) for name in names}
    facts = [n for n in names if info[n]["dates"]]
    masters = [n for n in names if n not in facts]
    edges = _edges(workspace, names)

    # References from a fact to a master's unique column.
    references: dict[tuple[str, str], tuple[str, str]] = {}
    for e in edges:
        if e["left"] in facts and e["right"] in masters and e["right_unique"]:
            references.setdefault((e["left"], e["left_on"]), (e["right"], e["right_on"]))
    # One role written twice — an id and a name resolving to the same master
    # row — is one role.
    aliases: set[tuple[str, str]] = set()
    by_table_master: dict[tuple[str, str], list[str]] = {}
    for (table, column), (master, _) in references.items():
        by_table_master.setdefault((table, master), []).append(column)
    for (table, master), columns in by_table_master.items():
        if len(columns) < 2:
            continue
        master_frame = frames[master]
        master_key = info[master]["keys"][0] if info[master]["keys"] else None
        if master_key is None:
            continue
        resolved = {}
        for column in columns:
            _, via = references[(table, column)]
            lookup = dict(zip(master_frame[via].cast(pl.String).to_list(), master_frame[master_key].cast(pl.String).to_list()))
            resolved[column] = [lookup.get(None if v is None else str(v)) for v in frames[table][column].to_list()]
        ordered = sorted(columns, key=lambda c: (not reference_shaped(c), frames[table].columns.index(c)))
        for other in ordered[1:]:
            pairs = [(a, b) for a, b in zip(resolved[ordered[0]], resolved[other]) if a is not None and b is not None]
            if pairs and sum(a == b for a, b in pairs) / len(pairs) >= ALIAS_AGREEMENT:
                aliases.add((table, other))
    role_refs = {k: v for k, v in references.items() if k not in aliases}
    referenced_fact_columns = {(e["left"], e["left_on"]) for e in edges if e["right"] in facts}

    # Parties: a master several columns point at. A master pointed at once per
    # table is a counterparty (the vendor), not a cast of roles.
    per_master: dict[str, list[tuple[str, str]]] = {}
    for (table, column), (master, _) in role_refs.items():
        per_master.setdefault(master, []).append((table, column))
    party_masters = {m for m, cols in per_master.items()
                     if any(sum(1 for t, _ in cols if t == table) >= 2 for table, _ in cols)}
    roles: list[dict] = []
    for (table, column), (master, _) in role_refs.items():
        if master in party_masters:
            roles.append({"table": table, "column": column, "master": master})
    # People with no master: a column named like a reference, repeating, that
    # resolves nowhere. An approver list kept outside the employee file is
    # still a cast of roles.
    for table in facts:
        for column in frames[table].columns:
            if (table, column) in references or (table, column) in referenced_fact_columns:
                continue
            if not reference_shaped(column) or column in info[table]["keys"]:
                continue
            if column in info[table]["dates"] or column in info[table]["amounts"]:
                continue
            values = frames[table][column].drop_nulls()
            # A person recurs: a dozen approvers sign forty claims. A column
            # that rarely repeats is a document reference, not a cast.
            if values.is_empty() or values.n_unique() > 0.5 * values.len():
                continue
            roles.append({"table": table, "column": column, "master": None})

    # What is left as a category: not a reference, not a role, and not one
    # column restated by another (a department and its cost centre, an
    # approver's id and name) — those are one category under two headings.
    role_columns = {(r["table"], r["column"]) for r in roles}
    for table in names:
        typed = info[table]
        excluded = {c for (t, c) in [*references, *referenced_fact_columns, *aliases] if t == table}
        excluded |= {c for (t, c) in role_columns if t == table}
        typed["dimensions"] = [c for c in typed["dimensions"] if c not in excluded]
        typed["statuses"] = [c for c in typed["statuses"] if c not in excluded]
        frame = frames[table]
        anchors = [c for (t, c) in role_columns if t == table] + list(typed["dimensions"])
        for index, first in enumerate(anchors):
            for second in anchors[index + 1:]:
                if second not in typed["dimensions"] or (table, second) in aliases:
                    continue
                pair = frame.select(first, second).drop_nulls()
                distinct = pair[first].n_unique()
                if distinct > 1 and pair[second].n_unique() == distinct and pair.unique().height == distinct:
                    aliases.add((table, second))
        typed["dimensions"] = [c for c in typed["dimensions"] if (table, c) not in aliases]

    counterparties = []
    for master in sorted(set(per_master) - party_masters):
        mframe = frames[master]
        key_column = next(iter({via for (_, _), (m, via) in role_refs.items() if m == master}), None)
        strings = [c for c in mframe.columns if mframe[c].dtype == pl.String and c != key_column]
        name_column = next((c for c in strings if set(_tokens(c)) & _NAME_TOKENS), strings[0] if strings else None)
        status_column = next((c for c in info[master]["statuses"] if mframe[c].n_unique() >= 2), None)
        counterparties.append({
            "master": master, "key": key_column, "name": name_column, "status": status_column,
            "references": [{"table": t, "column": c} for (t, c), (m, _) in sorted(role_refs.items()) if m == master],
        })

    # Children and the chain.
    fact_edges = [e for e in edges if e["left"] in facts and e["right"] in facts and e["right_unique"]]
    children = {}
    for e in fact_edges:
        if not e["left_unique"]:
            children.setdefault(e["left"], {"table": e["left"], "parent": e["right"],
                                            "column": e["left_on"], "parent_column": e["right_on"]})
    members = [t for t in facts if t not in children]
    first_date = {t: _median_date(frames[t], info[t]["dates"][0]) for t in members}
    members.sort(key=lambda t: (first_date[t] is None, first_date[t] or 0, t))
    chain = _chain(workspace, members, fact_edges, frames, info)

    lookups = []
    for table in masters:
        mframe = frames[table]
        strings = [c for c in mframe.columns if mframe[c].dtype == pl.String]
        numbers = [c for c in mframe.columns if mframe[c].dtype.is_numeric()]
        if mframe.height > MAX_LOOKUP_ROWS or len(strings) != 1 or len(numbers) != 1:
            continue
        domain = set(mframe[strings[0]].drop_nulls().to_list())
        for party in sorted(party_masters):
            pframe = frames[party]
            for via in pframe.columns:
                if pframe[via].dtype == pl.String and domain and domain <= set(pframe[via].drop_nulls().to_list()):
                    lookups.append({"table": table, "key": strings[0], "limit": numbers[0], "party": party, "via": via})

    for table in names:
        info[table].pop("profiles", None)
    return {
        "version": MAP_VERSION,
        "tables": {t: {**info[t], "kind": "child" if t in children else ("fact" if t in facts else "master")} for t in names},
        "facts": facts,
        "masters": masters,
        "children": list(children.values()),
        "roles": roles,
        "aliases": [{"table": t, "column": c} for t, c in sorted(aliases)],
        "counterparties": counterparties,
        "lookups": lookups,
        "chain": chain,
    }


def _chain(workspace, members, fact_edges, frames, info) -> dict:
    """Join the transaction tables into one frame, one row per root record."""
    if not members:
        return {"root": None, "tables": [], "recipe": None, "columns": {}, "steps": [], "links": [], "unchained": []}
    root = members[0]
    joined = [root]
    plan = []
    unchained = []
    for table in members[1:]:
        if len(plan) >= MAX_CHAIN_JOINS:
            unchained.append(table)
            continue
        options = []
        for e in fact_edges:
            # ``table`` cites a chained table, and its citing column is unique.
            if e["left"] == table and e["right"] in joined and e["left_unique"]:
                options.append((e["right"], e["right_on"], e["left_on"], e["left_nulls"]))
            # A chained table cites ``table``'s key.
            if e["right"] == table and e["left"] in joined:
                options.append((e["left"], e["left_on"], e["right_on"], int(frames[table][e["right_on"]].null_count())))
        if not options:
            unchained.append(table)
            continue
        options.sort(key=lambda o: (int(frames[o[0]][o[1]].null_count()), o[3], o[0], o[1], o[2]))
        source, source_column, column, _ = options[0]
        plan.append({"table": table, "source": source, "source_column": source_column, "column": column})
        joined.append(table)
    if not plan:
        columns = {f"{root}.{c}": c for c in frames[root].columns}
        return {"root": root, "tables": [root], "recipe": None, "columns": columns,
                "steps": _steps(workspace, None, [root], columns, frames, info),
                "links": [], "unchained": unchained}
    digest = _sha([(p["table"], p["source"], p["source_column"], p["column"]) for p in plan], 8)
    name = f"profile_chain_{root}_{digest}"
    mapping = {(root, c): c for c in frames[root].columns}
    current_columns = list(frames[root].columns)
    joins_ = []
    previous = root
    for index, step in enumerate(plan):
        right = step["table"]
        left_on = mapping[(step["source"], step["source_column"])]
        right_cols = list(frames[right].columns)
        suffix = join_suffix(current_columns, right_cols, [step["column"]], right)
        for c in right_cols:
            if c == step["column"]:
                mapping[(right, c)] = left_on
            elif c in current_columns:
                mapping[(right, c)] = f"{c}{suffix}"
            else:
                mapping[(right, c)] = c
        current_columns = current_columns + [mapping[(right, c)] for c in right_cols if c != step["column"]]
        join_name = name if index == len(plan) - 1 else f"{name}_{index + 1}"
        joins_.append({"name": join_name, "left": previous, "right": right, "how": "left",
                       "left_on": [left_on], "right_on": [step["column"]]})
        previous = join_name
    recipe = {"version": 1, "name": name, "root": root, "joins": joins_}
    try:
        recipe = validate_input(workspace, recipe)
        view = InputWorkspace(workspace, [recipe], validated=True)
        present = set(view.get_frame(name).columns)
    except WorkspaceError:
        columns = {f"{root}.{c}": c for c in frames[root].columns}
        return {"root": root, "tables": [root], "recipe": None, "columns": columns,
                "steps": _steps(workspace, None, [root], columns, frames, info),
                "links": [], "unchained": [p["table"] for p in plan] + unchained}
    columns = {f"{t}.{c}": v for (t, c), v in mapping.items() if v in present}
    links: list[dict] = []
    chain_link = {(p["table"], p["column"]) for p in plan} | {(p["source"], p["source_column"]) for p in plan}
    for e in fact_edges:
        if e["left"] in joined and e["right"] in joined and (e["left"], e["left_on"]) not in chain_link:
            if f"{e['left']}.{e['left_on']}" in columns and not any(
                    l["table"] == e["left"] and l["column"] == e["left_on"] for l in links
            ):
                links.append({"table": e["left"], "column": e["left_on"], "cites": e["right"],
                              "chain_column": columns[f"{e['left']}.{e['left_on']}"]})
    return {
        "root": root, "tables": joined, "recipe": recipe, "columns": columns,
        "steps": _steps(workspace, recipe, joined, columns, frames, info),
        "links": links, "unchained": unchained,
    }


def _steps(workspace, recipe, tables, columns, frames, info) -> list[dict]:
    """Every chain date in the order the data puts it, with who did it."""
    frame = (InputWorkspace(workspace, [recipe], validated=True).get_frame(recipe["name"])
             if recipe else frames[tables[0]])
    root_date = columns[f"{tables[0]}.{info[tables[0]]['dates'][0]}"]
    base = frame.select(pl.col(root_date).cast(pl.Date, strict=False).alias("__root"))
    candidates = []
    for order, table in enumerate(tables):
        for position, column in enumerate(info[table]["dates"]):
            chain_column = columns.get(f"{table}.{column}")
            if chain_column is None:
                continue
            days = frame.select(
                (pl.col(chain_column).cast(pl.Date, strict=False) - base["__root"]).dt.total_days().alias("d")
            )["d"].drop_nulls()
            median = float(days.median()) if days.len() else None
            candidates.append((median is None, median or 0.0, order, position, table, column, chain_column))
    candidates.sort()
    steps = [{"id": f"S{i + 1:02d}", "table": c[4], "column": c[5], "chain_column": c[6],
              "median_day": None if c[0] else c[1], "person": None, "person_chain_column": None}
             for i, c in enumerate(candidates)]
    return steps


def attach_people(data_map: dict) -> dict:
    """Pair each step with the role column that says who did it."""
    chain = data_map["chain"]
    steps = chain.get("steps") or []
    roles = [r for r in data_map["roles"] if r["table"] in (chain.get("tables") or [])]
    used = set()
    for step in steps:
        subject = _subject(step["column"])
        best = None
        for role in roles:
            if role["table"] != step["table"] or (role["table"], role["column"]) in used:
                continue
            other = _subject(role["column"])
            if not subject or not other:
                continue
            score = len(subject & other) / len(subject | other)
            if score > 0 and (best is None or score > best[0]):
                best = (score, role)
        if best:
            used.add((best[1]["table"], best[1]["column"]))
            step["person"] = best[1]["column"]
            step["person_chain_column"] = chain["columns"].get(f"{best[1]['table']}.{best[1]['column']}")
    # A role no date names is the one that raised the record: it belongs to its
    # table's first step, when that step has nobody yet.
    for role in roles:
        if (role["table"], role["column"]) in used:
            continue
        first = next((s for s in steps if s["table"] == role["table"]), None)
        if first is not None and first["person"] is None:
            used.add((role["table"], role["column"]))
            first["person"] = role["column"]
            first["person_chain_column"] = chain["columns"].get(f"{role['table']}.{role['column']}")
    return data_map


# --------------------------------------------------------------------------- #
# profile definitions
# --------------------------------------------------------------------------- #
def _definition(title: str, note: str, table: str, test: str, params: dict, alignment: dict | None = None) -> dict:
    identity = {"test": test, "params": params, "table": table if alignment is None else None,
                "alignment": None if alignment is None else {k: v for k, v in alignment.items() if k != "name"}}
    semantic = f"{PROFILE_PREFIX}{_sha(identity, 16)}"
    definition = {
        "title": title, "kind": "analytics", "table": table,
        "spec": {"test": test, "params": params}, "note": note, "semantic_id": semantic,
    }
    if alignment is not None:
        definition["alignment"] = alignment
    return definition


def _single_join(workspace: Workspace, table: str, joins_: list[dict], tag: str) -> dict | None:
    digest = _sha([tag, table, joins_], 8)
    name = f"profile_{tag}_{table}_{digest}"
    previous = table
    steps = []
    for index, join in enumerate(joins_):
        join_name = name if index == len(joins_) - 1 else f"{name}_{index + 1}"
        steps.append({"name": join_name, "left": previous, "how": "left", **join})
        previous = join_name
    try:
        return validate_input(workspace, {"version": 1, "name": name, "root": table, "joins": steps})
    except WorkspaceError:
        return None


def data_steps(data_map: dict) -> list[dict]:
    """The dated steps the chain records, for the cycle turn to name.

    Each carries its table's own column names (not the chain frame's), because
    a cycle population names a base table and its columns.
    """
    attach_people(data_map)
    out = []
    for step in data_map["chain"].get("steps") or []:
        columns = [step["column"], *([step["person"]] if step.get("person") else [])]
        out.append({"id": step["id"], "table": step["table"], "columns": columns,
                    "median_day": step.get("median_day")})
    return out


def profile_digest(workspace: Workspace, tables: Iterable[str] | None = None) -> list[dict]:
    """What the population profile shows, computed now, for the reading turn.

    The reading runs before the profile is executed as saved analyses, and it
    is the turn that most needs to have read it: a requisition never ordered is
    "normal mid-cycle state" to a turn that cannot see that every other one was
    ordered within thirteen days. Each entry is the summary a profile analysis
    computes, bounded exactly as the memo receives it — never its rows.
    """
    from .. import analysis_payloads

    mapping = build_data_map(workspace, tables)
    digest = []
    for index, definition in enumerate(profile_definitions(workspace, mapping), 1):
        try:
            payload = analysis_payloads.compute_payload(workspace, {**definition, "id": f"P{index:02d}"})
        except Exception:  # noqa: BLE001 - a profile entry that will not compute is left out
            continue
        if payload.get("error"):
            continue
        aggregate = payload.get("aggregate")
        recipe = definition.get("alignment")
        frame = definition["table"]
        if recipe:
            joined = [j["right"] for j in recipe.get("joins") or []]
            frame = f"{recipe['root']} joined to {', '.join(joined)}"
        digest.append({
            "ref": f"P{index:02d}",
            "title": definition["title"],
            "frame": frame,
            "test": definition["spec"]["test"],
            "verdict": payload.get("verdict_text") or payload.get("verdict"),
            "stats": payload.get("stats") or [],
            **({
                "columns": aggregate.get("columns"),
                "rows": aggregate.get("rows"),
                "groups_withheld": aggregate.get("groups_withheld"),
                "rows_withheld": aggregate.get("rows_withheld"),
            } if isinstance(aggregate, Mapping) else {}),
        })
    return digest


def is_profile(analysis: Mapping) -> bool:
    return str(analysis.get("semantic_id") or "").startswith(PROFILE_PREFIX)


def profile_definitions(workspace: Workspace, data_map: dict) -> list[dict]:
    """Saved-analysis definitions describing the population the map found."""
    attach_people(data_map)
    tables = data_map["tables"]
    chain = data_map["chain"]
    out: list[dict] = []
    chain_tables = chain.get("tables") or []
    recipe = chain.get("recipe")
    frame_name = recipe["name"] if recipe else (chain_tables[0] if chain_tables else None)
    alignment = recipe
    steps = chain.get("steps") or []
    columns = chain.get("columns") or {}

    if frame_name:
        measures = [columns[f"{t}.{_measure(tables[t])}"] for t in chain_tables
                    if _measure(tables[t]) and f"{t}.{_measure(tables[t])}" in columns]
        if len(measures) >= 2:
            out.append(_definition(
                "Value at each step of the chain",
                "What each step carried forward from the one before: equal, more, less, or nothing at all.",
                frame_name, "chain_reconciliation", {"columns": measures}, alignment))
        dates = [s["chain_column"] for s in steps]
        if len(dates) >= 2:
            out.append(_definition(
                "Days taken by each step",
                "How long each step of the process takes in the order the dates put it, and the rows where a step came first.",
                frame_name, "step_durations", {"columns": dates}, alignment))
            out.append(_definition(
                "Weekend and month-end share of each date",
                "Whether the dates follow a working week, which says whether they were stamped or keyed.",
                frame_name, "calendar_profile", {"columns": dates}, alignment))
        markers = _markers(steps, chain.get("links") or [])
        if len(markers) >= 2:
            out.append(_definition(
                "Steps left blank while a later step happened",
                "A step with no record on a row that went on to a later step was skipped, not pending.",
                frame_name, "skipped_steps", {"columns": markers}, alignment))
        people = [s["person_chain_column"] for s in steps if s.get("person_chain_column")]
        others = [columns[f"{r['table']}.{r['column']}"] for r in data_map["roles"]
                  if r["table"] in chain_tables and f"{r['table']}.{r['column']}" in columns]
        people = list(dict.fromkeys([*people, *others]))
        if len(people) >= 2:
            out.append(_definition(
                "Who acts in each role",
                "Each person's count in each role, in process order: who raises, who checks, who approves.",
                frame_name, "role_matrix", {"columns": people}, alignment))
            out.append(_definition(
                "The same person in two roles",
                "Roles usually held by one person describe how the process is staffed; roles almost never held by one person and held by one here are exceptions.",
                frame_name, "role_overlap", {"columns": people}, alignment))
        keys = [columns[f"{t}.{tables[t]['keys'][0]}"] for t in chain_tables
                if tables[t]["keys"] and f"{t}.{tables[t]['keys'][0]}" in columns]
        if len(keys) >= 2:
            out.append(_definition(
                "Identifiers carried along the chain",
                "Whether each record's number follows the record before it, and which ones were numbered apart.",
                frame_name, "id_series", {"columns": keys}, alignment))
        dims = [(t, d) for t in chain_tables for d in tables[t]["dimensions"]]
        pairs = [(a, b) for i, a in enumerate(dims) for b in dims[i + 1:] if a[0] != b[0]][:MAX_CROSSTABS]
        for (ta, da), (tb, db) in pairs:
            ca, cb = columns.get(f"{ta}.{da}"), columns.get(f"{tb}.{db}")
            if ca and cb:
                out.append(_definition(
                    f"{da} against {db}",
                    "Whether one category predicts the other, which says what each actually records.",
                    frame_name, "crosstab", {"rows": ca, "columns": cb}, alignment))

    for table in [*chain_tables, *[c["table"] for c in data_map["children"]]]:
        t = tables[table]
        measure = _measure(t)
        party = next((r["column"] for r in data_map["roles"] if r["table"] == table), None)
        if measure and table == (chain_tables[0] if chain_tables else None):
            out.append(_definition(
                f"{measure} by size band", "How few records carry most of the value.",
                table, "value_bands", {"column": measure}))
        for dimension in t["dimensions"]:
            params = {"dimension": dimension}
            if measure:
                params["measure"] = measure
            if party:
                params["party"] = party
            out.append(_definition(
                f"{measure or 'Records'} by {dimension}", f"Where {table}'s value sits by {dimension}, and how many people stand behind each.",
                table, "breakdown", params))
        if measure and t["quantities"]:
            for dimension in t["dimensions"]:
                if 3 <= _distinct(workspace, table, dimension) < max(t["rows"] // 2, 4):
                    out.append(_definition(
                        f"{measure} per {t['quantities'][0]} within each {dimension}",
                        "A price that departs from what every other order paid for the same thing.",
                        table, "ratio_consistency",
                        {"numerator": measure, "denominator": t["quantities"][0], "group": dimension}))
                    break

    if chain_tables:
        head, tail = chain_tables[0], chain_tables[-1]
        for table, date, label in ((head, tables[head]["dates"][0], "raised"),
                                   (tail, _last_step_date(steps, tail) or tables[tail]["dates"][-1], "settled")):
            measure = _measure(tables[table])
            if measure:
                out.append(_definition(
                    f"{measure} by month of {date}", f"When value was {label}, month by month.",
                    table, "period_compare", {"date_column": date, "value_column": measure, "period": "month"}))

    for counterparty in data_map["counterparties"]:
        refs = [r for r in counterparty["references"] if r["table"] in chain_tables]
        if not refs or not counterparty["key"]:
            continue
        ref = max(refs, key=lambda r: chain_tables.index(r["table"]))
        measure = _measure(tables[ref["table"]])
        aligned = _single_join(workspace, ref["table"], [{"right": counterparty["master"], "left_on": [ref["column"]],
                                                          "right_on": [counterparty["key"]]}], "party")
        if aligned is None:
            continue
        for dimension in [c for c in (counterparty["name"], counterparty["status"]) if c]:
            params = {"dimension": dimension}
            if measure:
                params["measure"] = measure
            out.append(_definition(
                f"{measure or 'Records'} by {counterparty['master']} {dimension}",
                f"Where {ref['table']}'s value went by {counterparty['master']}, and to which status.",
                aligned["name"], "breakdown", params, aligned))

    for lookup in data_map["lookups"]:
        for role in data_map["roles"]:
            if role["master"] != lookup["party"]:
                continue
            measure = _measure(tables[role["table"]])
            party_key = tables[lookup["party"]]["keys"][0] if tables[lookup["party"]]["keys"] else None
            if not measure or not party_key:
                continue
            aligned = _single_join(workspace, role["table"], [
                {"right": lookup["party"], "left_on": [role["column"]], "right_on": [party_key]},
                {"right": lookup["table"], "left_on": [lookup["via"]], "right_on": [lookup["key"]]},
            ], "authority")
            if aligned is None:
                continue
            frame = InputWorkspace(workspace, [aligned], validated=True).get_frame(aligned["name"])
            limit_column = next((c for c in frame.columns if c == lookup["limit"] or c.startswith(f"{lookup['limit']}_")), None)
            signer = next((c for c in frame.columns if c == lookup["via"] or c.startswith(f"{lookup['via']}_")), None)
            if limit_column is None or signer is None:
                continue
            covered = frame.filter(pl.col(role["column"]).is_not_null())
            if covered.is_empty() or covered[limit_column].null_count() / covered.height > 1 - MIN_AUTHORITY_COVERAGE:
                continue
            out.append(_definition(
                f"{measure} by band against who signed as {role['column']}",
                f"Whether {role['column']} signs within the limit the {lookup['table']} gives their {lookup['via']}.",
                aligned["name"], "authority_grid",
                {"amount": measure, "limit": limit_column, "signer": signer}, aligned))

    seen = set()
    unique = []
    for definition in out:
        if definition["semantic_id"] not in seen:
            seen.add(definition["semantic_id"])
            unique.append(definition)
    return unique


def _measure(table: Mapping) -> str | None:
    amounts = table.get("amounts") or []
    return amounts[0] if amounts else None


def _distinct(workspace: Workspace, table: str, column: str) -> int:
    return int(workspace.get_frame(table)[column].n_unique())


_TERM_TOKENS = frozenset({"due", "expiry", "expires", "maturity", "deadline"})


def _last_step_date(steps: list[dict], table: str) -> str | None:
    """The last event on ``table``'s rows, not a term it was due by."""
    mine = [s for s in steps if s["table"] == table and not set(_tokens(s["column"])) & _TERM_TOKENS]
    return mine[-1]["column"] if mine else None


def _markers(steps: list[dict], links: list[dict]) -> list[str]:
    """Columns that record each step happening, in process order.

    A reference to another record is placed with the step that creates the
    record it cites: a requisition's PO number is recorded when the PO is
    raised, so a requisition never ordered has not skipped anything, while an
    invoice paid without citing its goods receipt has.
    """
    out: list[str] = []
    placed = set()
    for step in steps:
        out.append(step["chain_column"])
        if step.get("person_chain_column"):
            out.append(step["person_chain_column"])
        if step["table"] not in placed:
            placed.add(step["table"])
            out.extend(link["chain_column"] for link in links if link["cites"] == step["table"])
    return list(dict.fromkeys(out))
