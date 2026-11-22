# Generating the EDA memo from the analysis workflow

Status: design analysis, 21 November 2026. Nothing here is implemented.

The target is [`sample-procurement/eda-benchmark/memo.html`](sample-procurement/eda-benchmark/memo.html),
an exploratory memo written by hand over the procurement pack, and the key in
its [README](sample-procurement/eda-benchmark/README.md) (items D, V, C, A, E,
L and I). This document works back from that memo to the workflow: what each
part of it is made of, what `analysis_workflow_v1` produces today, what a
deterministic pass can already compute, and what has to change for the
workflow to write a memo of that kind.

The short version: almost every measurement in the benchmark is computable
without a model, from the profiler and the relationship evidence the workflow
already has. A prototype sweep with no procurement-specific names reproduced
them. The model's irreplaceable work is reading those measurements: deciding
what a fact means for the audit, which records are exceptions rather than
ordinary operations, what the data cannot answer, and how to say it. Today the
workflow spends most of its model budget on the opposite: turning assertions
into specs one frame at a time, while the memo writer never sees an aggregate.

## 1. What the benchmark memo is made of

The memo was produced in about eight rounds of: profile, ask a question,
compute in Polars, read the aggregate, decide what to look at next. Sorted by
the kind of work each part needed:

| Kind of work | Benchmark items | Example |
| --- | --- | --- |
| Deterministic measurement, generic | D-01, D-02, D-04, D-05, D-06, V-01–V-03, V-05, C-01–C-03, A-01–A-04, most of E | Step durations between every consecutive pair of dates on the chain, with the records that run backwards |
| Measurement, then a reading only a model can give | D-03, D-04, D-05, V-04, E-14 | "Every PO equals its estimate" is a count; "so a PO-within-estimate test proves nothing" is a reading |
| Synthesis across results | D-06, E-15, A-03 | The off-series chain is also the only invoice dated before its PO |
| Questions about the whole column inventory | L-01–L-06 | No field records a received quantity |
| Writing for a reader | Summary, I-01–I-05, questions for management | Where to point the testing, and why |

Three observations about how the memo was made matter for the design.

- **The most useful findings are about the data, not about exceptions.** D-03
  (PO equals estimate), D-04 (catalogue prices) and D-05 (keyed dates) change
  which tests are worth running. None is an exception, so none can come out of
  an assertion register.
- **Exceptions read better against the profile.** E-14 is three requisitions
  with no PO. It became a finding when set against C-01: every other
  requisition became a PO within 13 days, and these are 87 to 154 days old. E-05
  became meaningful when A-04 showed that Finance verifies everything else.
- **The model read aggregates, never populations.** Every round handed back a
  table of at most a few dozen rows: a breakdown, a duration profile, a matrix.
  That is the context boundary in `AGENTS.md` working as intended: compute
  locally, send the result.

## 2. What the workflow produces today

Run `20261121-125434-12dfc9` on the procurement workspace:

| Stage | Model calls | Prompt tokens | Output |
| --- | --- | --- | --- |
| Probe sweep over ~100 frame alignments | 0 | 0 | 21 measured nominations, all exception families |
| `analysis_reading` | 1 | 32k | kept 13, declined 8, authored 12, 5 unanswerable |
| `analysis_definitions`, one per frame | 11 (7 frames, 4 repairs) | 173k | specs for the 12 authored assertions |
| `analysis_summary` | 2 | 72k | the memo |

Against the benchmark key:

| Item | Today | Why |
| --- | --- | --- |
| D-01 | Yes | The memo reports statuses and the three unordered requisitions from table profiles. |
| D-02 | Partial | Populations are stated; the bridge is never computed. |
| D-03 | **Wrong** | The memo says "ordering controls held on the PO side — PO total within estimate". The 52-of-52 equality is read as a control working, when it means the test cannot fail. The APM's *Data analytics performed* section repeats it, so the misreading reaches planning. |
| D-04, D-05 | No | No family measures a ratio within a group or a calendar profile. |
| D-06 | Partial | `format_anomaly` flagged VINV001-202404; nothing ties it to its chain. |
| V-01–V-05 | No | Descriptive tests are excluded (`EXCLUDED_ANALYTICS_TEST_IDS`), and the library has no breakdown test. |
| C-01–C-03 | No | Date pairs are measured only as orderings that breach. The reading turn declined both nominations behind E-14 as "normal mid-cycle state", with no duration profile to check that against. |
| A-01, A-04 | No | No family looks across person columns. |
| A-02, A-03 | Partial | Breaches are found; the routing pattern and the CEO's share are not. |
| E-01–E-14 | 8 of 13 scoreable | P-05 lost to the single-table validator rule; P-04 declined; P-01 written against the wrong role (approver, not verifier); P-03 and P-06 never written; P-11 not expressible in the library. |
| L-01–L-06 | 5 of 6 | The reading turn's `unanswerable` section already does this well. |
| I-01–I-05 | Partial | "Further work required" lists procedures, not where to point the audit. |

The structural reasons are in the code:

- **Nothing descriptive is measured.** `probes.FAMILIES` is referential,
  comparison, equality, values, duplicates and format: every family looks for
  rows that fail. `period_compare` and `stratify` exist but are excluded from
  autonomous runs.
- **The memo writer cannot see an answer.** `analysis_results.bounded_result`
  keeps a verdict, counts and up to a few library statistics. A Python
  group-by records "12 result rows" and nothing else.
  `_summary_result_projection` passes on exactly that.
- **The memo's shape is fixed to findings.** `SUMMARY_SECTIONS` has four
  headings, all about exceptions and reliance. The current memo's only embed
  kind in use is `exception_table`, 14 times. Internal frame names such as
  `aligned_invoice_data_1398ec8146d6` reach the reader.
- **Most of the model budget goes to translation.** Each authored assertion
  already names its frame and columns. The definition stage turns them into
  specs one frame at a time, 16k tokens a call, about 35% of it the analytics
  catalog and its `oneOf` schema. It also fights the validator: the P-05 spec
  was correct and was rejected because its one column came from one side of
  the join, even though the rows it tests are invoices.

## 3. Measured: how far a deterministic sweep reaches

[`profile_sweep_prototype.py`](sample-procurement/eda-benchmark/profile_sweep_prototype.py)
is a model-free sweep with no procurement names in it. Column roles come from
`profiler.profile_column`, and relationships from the same
`joins.candidate_keys` / `diagnose` / `classify` that
`data.relationships_inferred` uses. It infers:

- **Facts** are tables with dates, and **masters** are tables without.
- A master referenced by two or more columns of one fact is a **party**, and
  those columns are its **roles**. A master referenced once is a
  **counterparty**.
- The largest summable numeric on a fact is its **measure**.
- Categoricals are **dimensions**.
- The **chain** is the facts in order of their first date, linked by the most
  complete key.

### Procurement

It reproduced, exactly:

| Family | What it computed | Items |
| --- | --- | --- |
| Chain and reconciliation | 55 → 52 → 52; PO equals estimate 52/52; invoice above PO 3, excess 12,553,800; 3 unlinked | D-01, D-02, D-03, E-07, E-14 |
| Single-valued statuses | PO, GRN and payment status each hold one value | D-01 |
| Value distribution | Bands, 15 rows to 80% of value | V-01 |
| Breakdowns via masters | Department, item, vendor (by name), top shares | V-02, V-03 |
| One person behind a group | Facilities 45.2% from one requester | V-02 |
| Two-way tables | Item × department, vendor × item | V-04 (the table; the reading is a model's) |
| Time | Monthly value per date column | V-05 |
| Calendar | Weekend share per date column, 20–33% | D-05 |
| Cycle | Every date on the chain put in order by its median, consecutive durations, records running backwards (4 and 2) | C-01, C-02, E-09, E-11 |
| Party activity | 19 of 20 staff act; 1005 idle | A-01 |
| Same person in two roles | Verifier the same at both ends 48/52; requester = verifier 4 | A-04, E-05 |
| Authority | Role → title → limit lookup, both over-limit sets, CEO 76.9% / 79.5% | A-02, A-03, E-01, E-02 |
| Ratio within a group | Amount ÷ quantity by item: 13 of 14 single-valued, PO2024127 at 37.5× | D-04, E-13 |
| Identifier series | Lockstep 51/52, REQ2024009 → PO2024004 off-series | D-06 |

It also found one fact the memo missed: the executive who financially
approved a requisition approved its invoice in 46 of 49 chains.

Of the fourteen exception patterns (E-01 to E-14), the sweep and the existing
probes together reach all but E-03, E-04 and E-06. All three are the same
shape: a step left blank on a row where a later step happened. That is one more
generic family (a skipped step), and with it the floor reaches every pattern
without a model turn. E-15, the chain that fails three controls, is a synthesis
across results and stays the reading turn's.

### Expenses

Run unchanged on the expenses sample, the sweep found department and cost
centre to be one field restated (Cramér's V 1.0), and the same 27% weekend
pattern. It also broke in four ways. Each is a requirement:

1. **Grain.** Claim lines are children of claims, so the chain compared a line
   amount with a claim total. One-to-many links must aggregate the child to the
   parent's grain ("lines sum to the claim") instead of extending the chain.
   The join diagnostics already measure cardinality.
2. **Column typing.** It took `delegated_limit_pkr` as the approval log's
   measure and `gl_account` as the postings' measure. Measures, limits, rates
   and codes need telling apart. The document schemas already carry the
   vocabulary for this (`identifier`, `date`, `amount`, `number`, `text`,
   `boolean`, added in `82be736`), and a table column should be typed in the
   same terms so cycle rulesets and EDA speak one language.
3. **Parties outside the master, or referenced by name.** The claimant is
   referenced by both `employee_id` and `employee_name`, which the sweep took
   for two roles. Approvers (`APR-…`) are not in the employee master (`EMP-…`)
   at all, so approval was never recognised as a role.
4. **Hierarchical identifiers.** `EXP-2025-001-L2` belongs to
   `EXP-2025-001`; a same-number check must compare prefixes.

None of these needs a model to compute. All four benefit from one cheap
confirmation of the inferred roles before the sweep runs (section 4.1).

## 4. Proposed design

The principle is the memo's own method, made bounded: **measure everything
cheap, read it once, write once.**

```text
data.relationships_inferred      exists
        │
analysis.data_mapped        NEW  roles, chain, grain, the order the data puts
        │                        the steps in; deterministic
planning.cycle_ready        MOVED  the cycle's shape: steps named from the
        │                        process documents, bound to the map by local code
analysis.profiled           NEW  descriptive and exception families, by step;
        │                        0 tokens
analysis.register_ready     CHANGED  floor = probes + profile exceptions;
        │                        the reading turn also characterises, explores
        │                        and outlines
analysis.definitions_ready  CHANGED  one batched code call for adds and explores
        │
analysis.executed           exists
        │
analysis.summarized         CHANGED  reads bounded aggregates; new skeleton;
        │                        new exhibit kinds
planning.apm_ready          reads the memo and the cycle
        │
planning.cycle_themed       NEW  places the APM's risk themes on the steps
        │
planning.rcm_ready          depends on the themed cycle
```

### 4.1 The data map

A deterministic capability that writes one run-durable record:

- **Column roles:** key, link, measure, quantity, limit, rate, code, party
  role, counterparty, dimension, status, date, each with a value type from the
  document-schema vocabulary.
- **Facts and masters, and the grain of each fact.**
- **The chain:** facts ordered by date, joined by the most complete key. One-to-one
  links extend the chain; one-to-many children are rolled up to their parent.
- **Lookups:** a small master that maps a party attribute to a limit, like the
  approval matrix.

The map is inferred as above. One optional model turn can keep or correct it:
it sees schema, profile aggregates and relationship evidence, never rows. It has
the same keep-or-decline shape `cycle_field_pairs` gave the linkage turn. It is
safe to skip, because the inferred map is its floor. On expenses it would fix
items 2 and 3 above. On procurement it has nothing to change. In a full audit
the cycle turn (4.2) already confirms the steps and their role columns, so this
turn is left with column typing alone. The standalone analysis workflow, which
has no cycle, keeps the whole turn.

### 4.2 The cycle and the data map

The cycle design and the data map describe the same process from two sides.
The cycle the procurement run drew has twelve steps. Nine of them correspond to
a date the prototype sweep put on the chain, and five of those carry the person
column the sweep found as a role. For example, "Approve committed value by
Financial Authority" is `FIN_APPROVED_BY_ID` with `FIN_APPROVAL_DATE`. The
cycle knows the names and order the SOP gives. The map knows which columns hold
each step and the order the data puts them in. Each should feed the other, and
they can, because neither needs the other's model output.

**The map feeds the cycle.** Today the cycle turn reads column names and writes
`populations[].columns` itself. Those are identifiers into the workspace, which
[`rcm-generation-redesign.md`](rcm-generation-redesign.md) rules out ("the
model names things; local code finds things"). With the map:

1. the map proposes data steps: each chain date in median order, with the
   person column of the same stem and the table it lives on;
2. the turn names the engagement's steps and assigns data steps to them by id;
3. local code writes the populations.

The comparison produces two findings for free:

- **A step the documents name but no data step carries has no record of its
  own.** On procurement there are three:
  - "Match invoice to PO and GRN" has link columns but no record that a match
    was made;
  - "Refer invoice excess to Procurement" has no referral record;
  - "Convert or withdraw approved requisition" has a status but no withdrawal.

  These are limits (L-03, L-06, and the missing referral the answer key notes
  under P-07), found by construction rather than recalled.
- **A data step no document step claims is a gap in the process description.**
  The invoice date, the date received and the due date have no step of their
  own, yet E-09 and E-11 live on exactly those dates.

**The cycle feeds the analysis.** Step names label the cycle exhibit, the role
matrix and every exception, in the vocabulary the matrix will later be written
in, so a procedure promoted into the matrix (`analysis.promotion`) already
names its `process`. The reading turn sees exceptions organised by step, which
is what would have stopped the E-14 decline. A step called "Convert or withdraw
approved requisition" says an outcome must be recorded, and three requisitions
have none.

So the order is the map, then the cycle's shape, then the analysis's model
turns. That means moving the shape ahead of the APM, and it can move because
the APM is a relay, not the source. Procurement's *Process flow and
understanding* opens "The Procurement SOP extract describes the following
flow" and paraphrases it. The cycle has two halves with different sources:

| Half | Fields | Source | Needs the APM |
| --- | --- | --- | --- |
| Shape | name, steps in order, document roles, populations, anchor | process documents, document types, the map | No |
| Themes | each planned risk theme on one step | the APM's risk sections | Yes |

- `planning.cycle_ready` (the shape) depends on `planning.context_ready`,
  `documents.types_classified` and `analysis.data_mapped`, not on
  `planning.apm_ready`. Its context swaps `current_apm` for the planning
  documents the APM preset already selects. It keeps the memorandum as an
  optional source, so a cycle redrawn on request after an auditor corrected the
  memorandum's process flow still follows the correction. `invalidate_on`
  moves from `planning:apm` to the planning context and the map.
- **Theme placement becomes `planning.cycle_themed`**, after the APM. It is the
  existing worker's placement half: steps fixed, one small turn.
  `planning.rcm_ready` depends on it, and `tests.cycle_ruleset_proposed` keeps
  the shape. The alternative is an APM template that writes key risks under
  step headings, which places them by structure with no turn.
- **In the audit graph, `analysis.register_ready` takes a partial edge on
  `planning.cycle_ready`** (`_PARTIAL_DEPENDENCIES`), as it already does on
  joins, so a missing cycle withholds nothing. The standalone analysis workflow
  has no edge and reads a cycle when one exists, the way the APM reads the memo.
- **The APM reads the cycle** and writes its process flow to agree with it. The
  cycle is not a guarded parent of the memorandum, which stays live.

What changes for the auditor:

- **The first cycle is drawn from the process documents, not the memorandum.**
  An engagement with no process document gets steps named from the map and the
  planning context. Today its memorandum would have had nothing better to
  paraphrase.
- **The analysis's model turns wait for the document branch and the planning
  context.** Stages already run one at a time in dependency order, so the run
  takes no longer.
- **The cycle artifact's structure is unchanged**, so the cycle page and the
  matrix's view of the cycle read it as before. Step 5 of
  `rcm-generation-redesign.md` and `audit-workflow-graph.md` need their premise
  updated.

**A smaller first step.** Feeding the map to the cycle needs none of the move:
the cycle stays after the APM and gains one source. That alone replaces the
model-written columns and finds the steps with no record. Moving the shape
ahead is what lets the analysis use the names.

### 4.3 The profile sweep

A deterministic capability, `analysis.profiled`, runs these families over the
map:

| Family | Output | Exceptions it also nominates |
| --- | --- | --- |
| Chain and reconciliation | Counts and measure at each link, equal/above/below, the bridge | Above previous step; unlinked and aged against the step's normal duration |
| Statuses | Value mix; single-valued columns | |
| Value distribution | Bands on round numbers; rows to 80% | |
| Breakdowns | Each dimension and counterparty name: count, value, share, top-k | Counterparty in a minority status, joined to paid transactions |
| One person behind a group | Groups whose value comes from one party | |
| Two-way tables | Dimension × dimension, with Cramér's V | |
| Time | Monthly value per date; empty months | |
| Calendar | Weekend and month-end share per date | |
| Cycle | Dates ordered by median; step durations | Steps run backwards; steps skipped while a later one happened |
| Party roles | Person × role matrix; idle parties | |
| Same person | Equality rates between role columns, within and across the chain | Requester in a checking role |
| Authority | Measure bands cut at the lookup's own limits × title; top signer's share | Over limit; no approver |
| Ratio within a group | Measure ÷ quantity by dimension; single-valued groups | Ratio far from its group |
| Identifier series | Lockstep across the chain; off-series records | |

Each output is an **observation**: a family, the columns it read, headline
numbers, a bounded aggregate table, a chart spec, and the exception keys if it
has any. Observations are saved as analyses of a new `profile` kind: spec, not
data, recomputable, citable by the memo's embeds, and visible on the Analysis
tab. That means revisiting the reason `EXCLUDED_ANALYTICS_TEST_IDS` gives for
leaving descriptive tests out ("a chart that nothing downstream can promote,
cite, or conclude from"). Under this design the memo cites them, and through
the memo the APM does too.

The exception nominations join the probes' nominations in the register floor,
deduplicated by the same `analysis_semantic_id` and flagged-row fingerprints.

### 4.4 The reading turn

`analysis_reading` stays the one turn that sees the whole engagement, and its
input grows from nominations to observation digests: headline numbers and the
small aggregates, never rows. Its current sections stay (keep, add, decline,
unanswerable), and three are added:

- **characterize:** facts about the data that change how it should be tested,
  each with its implication. This is where D-03, D-04 and D-05 come from.
- **explore:** follow-up questions the sweep did not anticipate, each in words
  with the frames it needs. For this pack, everything was anticipated; on other
  data it will not be, and this is the door.
- **outline:** which observations matter, grouped into memo sections, with the
  exhibit each section should carry.

A decline must now be argued against the profile. E-14 was declined as "normal
mid-cycle state" by a turn that could not see that 13 days is normal and 87 is
not. With the aged-unlinked observation in front of it, the same decline has to
contradict a number.

### 4.5 Authoring: one batched code call

Replace one definition turn per frame with one call. It writes Polars for every
`add` and `explore`, against named frames, each returning a result, a chart
spec and an outcome policy. Each runs locally before it is saved, and a failure
is repaired on its own. The library stays the sweep's vocabulary. Code is for
what the model authors, as Data Tests already do at 6k tokens a call.

Fix the single-table rule while doing this. "Reads columns from only one of the
joined tables" should be judged by the population the rows belong to, not by
where the columns came from.

### 4.6 Bounded aggregates the memo can read

A new context representation, `analysis_aggregate`, behind its own permission,
`allow_analysis_aggregates`. It carries a result's summary frame, capped at
about 30 rows, stored in `Analyses/.results/<id>.json` beside the exception
rows, and stamped with `result_sha1` so it goes stale exactly when the
conclusion does.

This is consistent with the context boundary: an aggregate is a result, not an
input. A group built from fewer than `MIN_CATEGORY_ROWS` rows restates rows, so
those groups are merged or withheld and reported as `groups_withheld`. That
follows the same rule the three row doors follow: say what was left out.

### 4.7 The memo

`SUMMARY_SECTIONS` becomes a core plus optional sections:

1. Summary
2. Data received (population, reconciliation, character)
3. Where the value is (distribution, categories, time)
4. How the process runs
5. People and authority
6. Exceptions
7. What the data cannot answer
8. Implications for the plan

Sections 3 to 5 are omitted when no observation supports them. A two-table
treasury pack has no party roles, and the validator should accept that rather
than demand an empty section. Every claim must still cite a supplied analysis.
Frame names are replaced by the tables they were built from before the writer
sees them.

The implications section is what the APM's "Data analytics performed" section
needs most. A list of procedures is no help to planning; "test the 18
requisitions over 10M individually" is.

### 4.8 Exhibits

The benchmark uses seven chart forms: horizontal bars with value labels, multi-series
lines, segmented share bars, shaded two-way tables, range plots,
log-scale strip plots, and a bridge. `ChartView` draws bar, line and pie. The
chart spec needs those seven types. `MemoView` renders them, and `memoDocx`
falls back to the table for each. The renderer in `memo.template.html` is a
working reference for all seven, including the light and dark tokens.

## 5. Cost

Estimates, not measurements, against the run in section 2:

| Stage | Today | Proposed |
| --- | --- | --- |
| Profile sweep and data map | 0 | 0, plus an optional ~5k confirmation |
| Cycle shape | one turn, after the APM | the same turn, moved; reads process documents instead of the memorandum |
| Theme placement | inside the cycle turn | one small turn after the APM, or none with step-organised risk headings |
| Reading | 32k | ~45–55k: digests instead of bare nominations |
| Definitions | 173k over 11 calls | ~15–25k in one call |
| Memo | 72k | ~90–110k: aggregates and more sections |
| **Total prompt** | **~277k** | **~150–195k** |

The saving comes from removing the per-frame translation turns. The memo gets
more expensive, and should: it is the one turn whose output the auditor reads.

## 6. Measuring progress

- **Observation coverage, automatic.** For each D, V, C, A and E item, check
  that the run's observations contain it, with the right count or record set.
  The sweep's numbers are exact, so this scorer can be strict.
- **Exception reach, by record.** `backend/tests/eda_answer_key.py` now
  matches the record IDs in `Analyses/.results/` rather than library
  signatures, so it credits P-08 (A-E140F01A flags exactly those three
  invoices), sees Python analyses, and can score P-11. On the run in section 2
  it reports 8 of 14.
- **Memo coverage, judged.** Whether the memo states each item, its reading
  included (D-03 must say the test cannot fail), scored as captured, partial,
  missed or wrong.
- **Generalization.** The expenses and treasury packs must not regress, and the
  four breakages in section 3 are the first test cases. A design tuned only to
  this memo would be the procurement answer key restated in code.

## 7. Phasing

Each phase is independently useful and measurable against the key.

1. **Fixes with no design change.** *Done.* The single-table validator rule, and the
   record-based scorer, which phase 2 onwards is measured with.
2. **Data map and profile sweep.** *Done.* `agent/data_map.py`,
   `analytics_profile.py` and the `analysis.profiled` capability. Run on the
   procurement workspace it saves 18 profile analyses with no model turn and
   takes the answer key from 8 of 14 to 11 of 14 (P-01, P-03, P-11). P-06's
   three invoices are flagged too, on the chain's requisition-rooted rows,
   which the key's population rule does not credit. Deterministic, with observations saved as
   `profile` analyses. The Analysis tab gains the profile before any memo
   change. The cycle turn gains the map as a source where it stands, after the
   APM, so local code binds its populations and the steps with no record
   surface (the smaller first step in 4.2).
3. **Aggregates and the memo.** *Done.* `analysis_results.bounded_aggregate`
   keeps each result's summary in its evidence sidecar; `allow_analysis_aggregates`
   and the `analysis_aggregates` source give it to the memo writer alone; the
   memo gains the three optional profile sections and "Implications for the
   plan"; recipe frames reach the writer as "requisitions joined to po_data,
   invoice_data". "What the data cannot answer" waits for phase 4, which is
   where the reading turn's unanswerable list reaches the memo. Live on
   procurement (two summary calls, 126k prompt tokens): the memo states the
   data's character (PO equals estimate on 52 of 52, prices fixed within 13 of
   14 items), carries all three profile sections and tells planning not to
   report PO-within-estimate as clean. The repair turn dropped the profile
   sections the first draft wrote, so a repair now carries `profile` and
   `implications` forward from the draft it repairs. Still short of the
   benchmark: weekend-heavy dates are read as "no after-hours keying" rather
   than "keyed, not stamped", and 37 embeds is too many to read.
4. **Reading and authoring.** *Done.* The reading turn is shown the profile's
   bounded summaries (`data_map.profile_digest`) and gains `characterize` and
   `explore`; declines are argued against the profile. One authoring unit and
   one `analysis.definitions` turn answer every authored assertion and explore
   question as Polars code, against frame schemas alone — no catalog, no
   figures — and the executor runs each before saving it. An explore answer is
   `informational` with a chart. The reading's characterize and unanswerable
   lists are kept beside the data (`analysis_reading.json`, stamped with every
   table's signature) and reach the memo, where "What the data cannot answer"
   is assembled by code. `outline` was dropped: the memo writer already has the
   profile and orders its own sections. Live on procurement: three model calls
   (reading 44k prompt tokens, authoring 15k, memo 67k) where phase 3 spent
   eleven definition turns and 173k tokens before the memo; the key goes from
   11 of 14 to 13 of 14, with P-05 partial. Ten authored analyses, four of them
   charted explore answers, none dropped. The weekend reading is now right —
   "dates were keyed rather than stamped" — and the memo names five things no
   column can answer (vendor status at payment date, who received the goods,
   credits and reversals, contract rates, the paying bank account). Still 37
   embeds, which phase 5 is for. Building it surfaced a latent bug: a
   definition with no `viz` could not be screened (`_cap_for(None)`), so an
   uninformative python result was kept rather than dropped.
5. **Exhibits.** *Done.* Each profile test declares its exhibit form in its
   `viz` — `hbar` (value labels, a chance line, a breach flag), `share`,
   `heatmap` (wide or long), `range`, `strip` (log scale) and `bridge`;
   `period_compare` keeps `line`. `exhibitCharts.ts` lays each out as marks
   (pure, tested as numbers) and `ExhibitChart.vue` draws them as SVG in the
   benchmark's palette, re-stepped for the dark sheet; `ChartView` hands it the
   new forms and keeps Chart.js for its own three. The Word export rasterises
   each exhibit with its paint inlined under the light theme, so the file keeps
   the chart rather than falling back to the table. The other half was volume:
   the assembler now places one table of flagged rows per finding and three
   exhibits per profile section, and the prompt asks for the proving procedure
   first. Live on procurement, one memo call (67k prompt tokens; one earlier
   attempt failed at the provider): 18 exhibits instead of 37 — nine charts,
   nine tables — and the role matrix, step durations, authority grid and value
   bridge are drawn rather than tabulated.
   **After phase 5: the expenses pack, and memo resilience.** First live run
   on the second pack: three calls, 118k prompt tokens, a sixteen-exhibit memo
   led by the right authority breach. Scored with the new expenses key
   (`EXPENSE_KEY`, the guide's ground-truth table), it reaches 6 of 8. What it
   exposed, and what changed:
   - With seven tables and none named, the six-table cap dropped
     `07_policy_limits` in name order. Reference-sized tables (at most
     `REFERENCE_SCOPE_ROWS` rows and a tenth of the largest) no longer count
     against the cap.
   - Four of eleven authored analyses aggregated `df["x"]` inside `.agg()`,
     which is one number for every group, and all four were dropped at
     execution. That is now a static error the authoring repair corrects, and an
     authoring response whose repair never arrives commits the items that
     passed.
   - The meal cap (E-02) and the 60-day deadline (E-06) were out of reach for
     a reason that was not a bug: they are cells of a six-row policy table,
     which is not a value domain, so the reading could ask what the policy sets
     but never saw 4,000 or 60. Decided: `analysis.reading` alone gains
     `allow_reference_table_rows`, the whole rows of a table at most
     `MAX_REFERENCE_TABLE_ROWS` rows and a tenth of the largest in scope —
     small is not enough, since every expenses population is under fifty rows.
     Live, the reading wrote the POL-01, POL-02 and POL-04 assertions with
     their numbers, the authoring turn wrote all of them with no code dropped,
     and the pack reaches **8 of 8** (prompt 135k over four calls). The meal
     test groups by employee-day and lists its claims, which the scorer now
     reads from a pluralised list column.
   - Memo resilience, from the failed procurement rewrite (a draft whose one
     fault was a procedure argued twice, lost after two six-minute repairs
     failed at the provider, 189k tokens): a repair is sent the reference
     sheet, the draft and the errors and returns only what it changes, and a
     repair that cannot be generated, or comes back worse, commits the draft
     with its faults recorded. Live on expenses, the repair took 9.9k prompt
     tokens and 24 seconds.
6. **The cycle's shape moves ahead.** It reads the process documents instead of
   the memorandum, theme placement splits off after the APM, and analysis takes
   a partial edge on the shape. Last because phase 2 already feeds the map to
   the cycle where it stands, which was most of the cycle's gain; this phase is
   for step names in the analysis, and it is the one with the widest reach
   across planning.

## 8. Decisions to make

- **Where observations live.** As `profile` analyses (citable, on the tab, one
  more kind in `Analyses/`) or run-durable like the register (cheaper, invisible).
  This document assumes analyses, because the memo cites them and a citation
  must resolve.
- **Whether the confirmation turn runs by default.** It costs little and fixes
  typing errors, but procurement needs no correction.
- **The aggregate threshold.** `MIN_CATEGORY_ROWS` reused, or a separate
  bound for groups.
- **How themes reach the steps.** A small placement turn after the APM, or an
  APM template whose key risks are written under the cycle's step headings, so
  placement is structural. The second removes a turn but changes a template
  firms edit.
- **Whether the shape moves at all.** Phase 2's smaller step (the map feeding
  the cycle where it stands) captures the cycle's gain. Phase 6 is only for the
  analysis's gain, step names in the memo and in every exception, and costs a
  graph change across planning.
- **A free-running analyst loop.** The benchmark was written that way: a model
  with a code tool, iterating. The bounded pipeline above reaches the same
  items with a fixed number of turns and a deterministic floor, and the
  `explore` section is the controlled version of the loop's freedom. A loop is
  worth revisiting only if the explore door turns out to be too narrow on real
  engagements.
