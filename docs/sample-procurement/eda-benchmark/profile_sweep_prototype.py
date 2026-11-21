"""Design prototype: a generic, model-free profile sweep over a workspace's tables.

Not product code. It exists to measure how much of the benchmark memo a
deterministic pass can compute before any model turn; see
``docs/eda-memo-redesign.md`` section 3 for what it reached and where it broke.

Nothing here names a procurement column. Column roles come from the app's own
profiler, and relationships from the same join diagnostics
``data.relationships_inferred`` uses. Point it at a workspace folder:

    uv run --no-project python docs/sample-procurement/eda-benchmark/profile_sweep_prototype.py \
        Workspaces/Users/local/Workspaces/procurement > sweep.json
"""
import json
import math
import re
import sys
from itertools import combinations
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
from app import profiler  # noqa: E402

from app.agent import joins  # noqa: E402

WS = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "Workspaces/Users/local/Workspaces/procurement"
def _read(p):
    return pl.read_excel(p) if p.suffix == ".xlsx" else pl.read_csv(p, try_parse_dates=True)
tables = {}
for p in sorted((WS / "Data").iterdir()):
    if p.suffix in (".xlsx", ".csv"):
        tables[re.sub(r"^\d+_", "", p.stem)] = _read(p)
entities = joins.entity_tokens(list(tables))
edges = []
for l in tables:
    for r in tables:
        if l == r:
            continue
        for lc, rc, _ in joins.candidate_keys(tables[l], tables[r], r, entities):
            if joins.classify(joins.diagnose(tables[l], tables[r], lc, rc)) == "strong":
                edges.append((l, lc, r, rc))
edges = sorted(set(edges))

prof = {t: {c["name"]: c for c in profiler.profile_table(df)["column_profiles"]} for t, df in tables.items()}
kind = lambda t, c: prof[t][c]["inferred_type"]
out = {}

# ---------------------------------------------------------------- roles
facts = [t for t in tables if any(kind(t, c) == "date" for c in tables[t].columns)]
masters = [t for t in tables if t not in facts]
keys = {t: [c for c in tables[t].columns if tables[t][c].n_unique() == tables[t].height and tables[t][c].null_count() == 0] for t in tables}
ref = {}  # (fact, column) -> master it resolves to
for l, lc, r, rc in edges:
    if l in facts and r in masters and rc in keys[r]:
        ref[(l, lc)] = r
party = {}  # master referenced by 2+ columns of one fact table: its columns are roles
for (t, c), m in ref.items():
    party.setdefault(m, {}).setdefault(t, []).append(c)
party = {m: v for m, v in party.items() if any(len(cs) >= 2 for cs in v.values())}
counterparty = sorted({m for (_, _), m in ref.items()} - set(party))
def measure(t):
    nums = [c for c in tables[t].columns if kind(t, c) == "numeric" and prof[t][c]["sum"] is not None and (t, c) not in ref]
    return max(nums, key=lambda c: float(tables[t][c].sum() or 0)) if nums else None
measures = {t: measure(t) for t in facts}
quantities = {t: [c for c in tables[t].columns if kind(t, c) == "numeric" and c != measures[t] and (t, c) not in ref and prof[t][c]["sum"] is not None] for t in facts}
dims = {t: [c for c in tables[t].columns if kind(t, c) == "categorical" and (t, c) not in ref and prof[t][c]["distinct_count"] > 1] for t in facts}
dates = {t: [c for c in tables[t].columns if kind(t, c) == "date"] for t in facts}
out["roles"] = dict(facts=facts, masters=masters, party=party, counterparty=counterparty, measures=measures, quantities=quantities, dims=dims)

# ---------------------------------------------------------------- the chain
# Facts joined key-to-key, ordered by when their first date column falls.
fact_edges = [(l, lc, r, rc) for l, lc, r, rc in edges if l in facts and r in facts and rc in keys[r]]
order = sorted(facts, key=lambda t: tables[t][dates[t][0]].median())
links = []
for a, b in zip(order, order[1:]):
    cand = [(l, lc, r, rc) for l, lc, r, rc in fact_edges if {l, r} == {a, b}]
    # later rows cite earlier ones, and the most complete citing column wins: a
    # link that is blank on some rows would drop them from the chain unseen
    cand.sort(key=lambda e: (e[2] != a, e[0] != b, tables[e[0]][e[1]].null_count()))
    links.append(cand[0])
chain = tables[order[0]].rename({c: f"{order[0]}.{c}" for c in tables[order[0]].columns})
for (l, lc, r, rc) in links:
    later = l if r in {order[0]} or f"{r}.{rc}" in chain.columns else r
    later, lcol, ecol = (l, lc, f"{r}.{rc}") if f"{r}.{rc}" in chain.columns else (r, rc, f"{l}.{lc}")
    right = tables[later].rename({c: f"{later}.{c}" for c in tables[later].columns})
    chain = chain.join(right, left_on=ecol, right_on=f"{later}.{lcol}", how="left", coalesce=False)
out["chain"] = dict(order=order, links=links, rows=chain.height)
pop = []
prev = None
for t in order:
    m = f"{t}.{measures[t]}"
    present = chain.filter(pl.col(f"{t}.{keys[t][0]}").is_not_null())
    pop.append(dict(table=t, rows=tables[t].height, linked=present.height, total=int(tables[t][measures[t]].sum())))
    if prev:
        both = chain.filter(pl.col(prev).is_not_null() & pl.col(m).is_not_null())
        pop[-1]["vs_previous"] = dict(equal=int((both[m] == both[prev]).sum()), above=int((both[m] > both[prev]).sum()), below=int((both[m] < both[prev]).sum()),
                                      excess=int((both[m] - both[prev]).clip(lower_bound=0).sum()), unlinked_previous=int(chain.filter(pl.col(prev).is_not_null() & pl.col(m).is_null()).height))
    prev = m
out["population"] = pop

# ---------------------------------------------------------------- statuses
out["single_valued"] = {t: [c for c in tables[t].columns if kind(t, c) == "categorical" and prof[t][c]["distinct_count"] == 1] for t in tables}
out["status_mix"] = {f"{t}.{c}": tables[t][c].value_counts(sort=True).rows() for t in facts for c in dims[t] if prof[t][c]["distinct_count"] <= 5}

# ---------------------------------------------------------------- value distribution of the head measure
head, hm = order[0], measures[order[0]]
v = tables[head][hm].drop_nulls().sort(descending=True)
edges_ = [b for b in (1e3, 1e4, 1e5, 1e6, 5e6, 1e7, 5e7, 1e8, 5e8, 1e9) if v.min() < b < v.max()]
bands = tables[head].with_columns(pl.col(hm).cut(edges_).alias("band")).group_by("band").agg(pl.len(), pl.col(hm).sum()).sort("band")
cum = (v.cum_sum() / v.sum()).to_list()
out["concentration"] = dict(rows=v.len(), top_10pct_share=round(cum[max(0, math.ceil(v.len() * .1) - 1)], 3), rows_for_80pct=next(i + 1 for i, x in enumerate(cum) if x >= .8), bands=bands.rows())

# ---------------------------------------------------------------- breakdowns
def breakdown(df, dim, m):
    g = df.group_by(dim).agg(pl.len().alias("n"), pl.col(m).sum().alias("v")).sort("v", descending=True)
    tot = g["v"].sum()
    return dict(dimension=dim, groups=g.height, top=g.row(0)[0], top_share=round(g["v"][0] / tot, 3), top3_share=round(g["v"].head(3).sum() / tot, 3), rows=g.head(10).rows())
bd = []
for t in facts:
    for d in dims[t]:
        if prof[t][d]["distinct_count"] > 5:
            bd.append(dict(table=t, **breakdown(tables[t], d, measures[t])))
    for (tt, c), m in ref.items():
        if tt == t and m in counterparty:
            name = next((x for x in tables[m].columns if tables[m][x].dtype == pl.String and x != keys[m][0]), keys[m][0])
            j = tables[t].join(tables[m], left_on=c, right_on=keys[m][0], how="left")
            bd.append(dict(table=t, via=m, **breakdown(j, name, measures[t])))
out["breakdowns"] = bd
# who dominates a dimension: one person behind a whole group
dom = []
for m, by in party.items():
    for t, cols in by.items():
        for d in dims[t]:
            if prof[t][d]["distinct_count"] <= 5:
                continue
            for c in cols:
                g = tables[t].group_by(d).agg(pl.col(c).n_unique().alias("people"), pl.col(measures[t]).sum().alias("v")).sort("v", descending=True)
                tot = g["v"].sum()
                for row in g.iter_rows(named=True):
                    if row["people"] == 1 and row["v"] / tot > .25:
                        dom.append(dict(table=t, dimension=d, group=row[d], role=c, share=round(row["v"] / tot, 3)))
out["single_person_groups"] = dom

# ---------------------------------------------------------------- association between dimensions (Cramér's V)
def cramers_v(df, a, b):
    ct = df.group_by(a, b).len()
    n = df.height; ra = df.group_by(a).len(); rb = df.group_by(b).len()
    full = ra.rename({"len": "na"}).join(rb.rename({"len": "nb"}), how="cross").with_columns((pl.col("na") * pl.col("nb") / n).alias("e"))
    obs = full.join(ct.rename({"len": "obs"}), on=[a, b], how="left").with_columns(pl.col("obs").fill_null(0))
    x2 = float(obs.select(((pl.col("obs") - pl.col("e")) ** 2 / pl.col("e")).sum()).item())
    k = min(ra.height, rb.height) - 1
    return round(math.sqrt(x2 / (n * k)), 3) if k > 0 else None
assoc = []
wide = chain
cat_cols = [f"{t}.{d}" for t in facts for d in dims[t] if 5 < prof[t][d]["distinct_count"]] + [f"{t}.{c}" for (t, c), m in ref.items() if m in counterparty]
for a, b in combinations(cat_cols, 2):
    sub = wide.select(a, b).drop_nulls()
    if a.split(".")[1] == b.split(".")[1]:
        continue
    assoc.append(dict(a=a, b=b, cramers_v=cramers_v(sub, a, b), a_groups=sub[a].n_unique(), b_groups=sub[b].n_unique()))
out["association"] = assoc

# ---------------------------------------------------------------- time
months = {}
for t in facts:
    for d in dates[t]:
        s = tables[t].group_by(pl.col(d).dt.truncate("1mo").alias("m")).agg(pl.col(measures[t]).sum().alias("v"), pl.len()).sort("m")
        months[f"{t}.{d}"] = [(str(r[0])[:7], r[1], r[2]) for r in s.drop_nulls("m").rows()]
out["months"] = months
out["weekend_share"] = {f"{t}.{d}": round(float((tables[t][d].drop_nulls().dt.weekday() >= 6).mean()), 3) for t in facts for d in dates[t]}

# ---------------------------------------------------------------- the cycle: every date on the chain, in the order the data puts them
dcols = [f"{t}.{d}" for t in order for d in dates[t]]
seq = sorted(dcols, key=lambda c: chain.select((pl.col(c) - pl.col(dcols[0])).dt.total_days().median()).item())
steps = []
for a, b in zip(seq, seq[1:]):
    x = chain.select((pl.col(b) - pl.col(a)).dt.total_days().alias("d"))["d"].drop_nulls()
    steps.append(dict(frm=a, to=b, n=x.len(), min=int(x.min()), med=float(x.median()), max=int(x.max()), before_previous=int((x < 0).sum())))
out["cycle"] = steps

# ---------------------------------------------------------------- roles and authority
for m, by in party.items():
    pm = {}
    for t, cols in by.items():
        for c in cols:
            for sid, n in tables[t].group_by(c).len().drop_nulls().rows():
                pm.setdefault(sid, {})[f"{t}.{c}"] = n
    idle = [k for k in tables[m][keys[m][0]].to_list() if k not in pm]
    out.setdefault("party", {})[m] = dict(people_acting=len(pm), idle=idle)
# the same person in two role columns of one chain row
pairs = []
role_cols = [f"{t}.{c}" for m, by in party.items() for t, cs in by.items() for c in cs]
for a, b in combinations(role_cols, 2):
    s = chain.select(a, b).drop_nulls()
    if s.height < 20:
        continue
    eq = int((s[a] == s[b]).sum())
    if eq:
        pairs.append(dict(a=a, b=b, same=eq, of=s.height, rate=round(eq / s.height, 3)))
out["same_person"] = sorted(pairs, key=lambda p: -p["rate"])
# a small lookup giving a numeric limit to a text attribute of the party master
limits = []
for lt in masters:
    df = tables[lt]
    texts = [c for c in df.columns if df[c].dtype == pl.String]; nums = [c for c in df.columns if df[c].dtype.is_numeric()]
    if df.height > 50 or len(texts) != 1 or len(nums) != 1:
        continue
    for m in party:
        for pc in tables[m].columns:
            if tables[m][pc].dtype == pl.String and set(df[texts[0]]) <= set(tables[m][pc]):
                for t, cols in party[m].items():
                    for c in cols:
                        j = (tables[t].join(tables[m], left_on=c, right_on=keys[m][0], how="left")
                             .join(df, left_on=pc, right_on=texts[0], how="left"))
                        covered = j.filter(pl.col(nums[0]).is_not_null())
                        if covered.height < 10:
                            continue
                        over = covered.filter(pl.col(measures[t]) > pl.col(nums[0]))
                        lim_vals = sorted(df[nums[0]].to_list())
                        band = pl.col(measures[t]).cut([x for x in lim_vals if x < 1e11])
                        grid = j.with_columns(band.alias("band")).group_by("band", pc).len().sort("band", pc)
                        top = j.group_by(pc).agg(pl.col(measures[t]).sum()).sort(measures[t], descending=True).row(0)
                        limits.append(dict(table=t, role=c, lookup=lt, via=pc, covered=covered.height, of=j.height, over=over.height, over_ids=over[keys[t][0]].to_list(),
                                           top_signer=top[0], top_share=round(top[1] / j[measures[t]].sum(), 3), grid_cells=grid.height))
out["authority"] = limits

# ---------------------------------------------------------------- a ratio within a group
ratios = []
for t in facts:
    for q in quantities[t]:
        for d in [x for x in tables[t].columns if kind(t, x) in ("categorical", "text") and (t, x) not in ref and 5 < prof[t][x]["distinct_count"] < tables[t].height]:
            r = tables[t].with_columns((pl.col(measures[t]) / pl.col(q)).alias("ratio"))
            g = r.group_by(d).agg(pl.col("ratio").n_unique().alias("distinct"), pl.len())
            single = g.filter((pl.col("distinct") == 1) & (pl.col("len") > 1)).height
            multi = g.filter(pl.col("len") > 1).height
            outl = r.with_columns(pl.col("ratio").median().over(d).alias("med")).filter(pl.col("ratio") > 3 * pl.col("med"))
            ratios.append(dict(table=t, ratio=f"{measures[t]}/{q}", group=d, groups_single_value=single, groups=multi, outliers=outl.select(keys[t][0], d, "ratio", "med").rows()))
out["ratios"] = ratios

# ---------------------------------------------------------------- identifiers moving together
idents = []
num = lambda c: pl.col(c).cast(pl.String).str.extract(r"(\d+)$").cast(pl.Int64)
kcols = [f"{t}.{keys[t][0]}" for t in order]
for a, b in zip(kcols, kcols[1:]):
    s = chain.select(a, b).drop_nulls()
    same = s.filter(num(a) == num(b))
    idents.append(dict(a=a, b=b, same_number=same.height, of=s.height, off_series=s.filter(num(a) != num(b)).rows()))
out["identifiers"] = idents

print(json.dumps(out, default=str, indent=1))
