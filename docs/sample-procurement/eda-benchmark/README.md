# EDA benchmark memo

`memo.html` is the exploratory data analysis this pack's six workbooks should
produce: what the population is, where the money goes, how the cycle runs, who
holds authority, and where the records break their own pattern. It was written
by hand, by an analyst working in Polars, and is the target the analysis
workflow is measured against. The work-back from this memo to the workflow is
[`docs/eda-memo-redesign.md`](../../eda-memo-redesign.md).

It is not a blind result. The exceptions section was written by someone who had
already read the answer key in [`FACILITATOR_GUIDE.md`](../FACILITATOR_GUIDE.md).
The data-character, profile, process and authority items below were found in
the data and are not in that key.

## Files

| File | What it is |
| --- | --- |
| `memo.html` | The memo. Open it in a browser; every exhibit has its data and the Polars behind it. |
| `memo.template.html` | The page, with `/*DATA*/` where the exhibit data goes. |
| `build_memo.py` | Computes every figure from `../data/*.xlsx` and writes `data.json` and `memo.html`. Deterministic. |
| `data.json` | The exhibit data the build computed. |
| `profile_sweep_prototype.py` | A design prototype: a generic, model-free sweep that recomputes most of the memo's measurements from any workspace folder. Not product code. |

Rebuild after changing the template or the computation:

```bash
uv run --no-project python docs/sample-procurement/eda-benchmark/build_memo.py
```

## The benchmark key

Each item is something the memo establishes. A generated memo is scored on
whether it states the item with the right population and figures. The exception
items carry their answer-key reference.

### Data received and its character

| Ref | The memo establishes |
| --- | --- |
| D-01 | A one-to-one chain: 55 requisitions, 52 POs, 52 invoices. Every PO closed, every GRN received, every invoice paid; nothing open except 3 approved requisitions never ordered. |
| D-02 | The population reconciles: 645.4M requisitioned, 35.4M never ordered, 610.0M ordered, 12.6M billed above PO, 622.5M paid. |
| D-03 | Every PO equals its requisition estimate (52 of 52), so a PO-within-estimate test cannot fail. |
| D-04 | 13 of 14 items carry one unit price on every PO, whichever vendor supplied them. |
| D-05 | 27.4% of the 566 dated events fall on a weekend, against 28.6% for random dates: the dates look keyed, not stamped. |
| D-06 | Requisition, PO and invoice numbers move in lockstep; REQ2024009 → PO2024004 → INV2024004 is off-series, carries the only off-format vendor invoice number (VINV001-202404), and is the only chain whose invoice predates its PO. |

### Where the money goes

| Ref | The memo establishes |
| --- | --- |
| V-01 | 18 requisitions over 10M hold 86.5% of the value; the 17 at 1M or less hold 1.1%. |
| V-02 | Facilities is 45.2% of value, all raised by one person; Procurement raises the most requisitions (19) at a median of 1.9M. |
| V-03 | Five vendors take 79.2% of payments and the largest 28.3%; two vendors not Active in the master were paid. |
| V-04 | Department and vendor do not describe the purchase: HR bought 3 of the 4 UPS replacements, vendors supply up to 7 unrelated items, each item comes from 2 to 5 vendors. |
| V-05 | Commitments come in two waves (January to March, September to November); payments peak in March and October; no requisition in May; no year-end rush. |

### How the cycle runs

| Ref | The memo establishes |
| --- | --- |
| C-01 | Requisition approval steps take 1 to 4 days, PO 2 to 13 (median 6.5), delivery 5 to 25; end to end a median 47 days (19 to 64). |
| C-02 | All 52 invoices were paid before their due date, 4 to 21 days early, a median 13, on 30-day terms. |
| C-03 | The 3 unordered requisitions are 87 to 154 days old at year end, when every other requisition became a PO within 13 days. |

### People and authority

| Ref | The memo establishes |
| --- | --- |
| A-01 | Each role is held by a fixed group; 19 of 20 staff act; the Head of Procurement acts in no role. |
| A-02 | Approval is routed by value band; the CEO signs 77% of requisition value and 80% of payments. |
| A-03 | Four of the five limit breaches are the Head of Treasury; the fifth is the CFO approving 64M against 10M, whose invoice went correctly to the CEO. |
| A-04 | In all 48 chains Finance verified, the same person verified the requisition and the invoice; the other 4 were verified by their requester. |

### Exceptions

| Ref | Exception | Records | Key |
| --- | --- | --- | --- |
| E-01 | Requisition financially approved above the approver's limit | REQ2024112, REQ2024127, REQ2024145 | P-02 |
| E-02 | Invoice approved above the approver's limit | INV2024127, INV2024140 | P-09 |
| E-03 | Procurement approval not recorded, requisition completed and ordered | REQ2024116, REQ2024130, REQ2024152 | P-03 |
| E-04 | Invoice paid with no approval recorded | INV2024104, INV2024131, INV2024154 | P-08 |
| E-05 | Requisition verified by the person who raised it | REQ2024108, REQ2024120, REQ2024134, REQ2024149 | P-01 |
| E-06 | Invoice paid with no goods receipt reference | INV2024110, INV2024132, INV2024147 | P-06 |
| E-07 | Invoice above its PO (12,553,800 excess) | INV2024106, INV2024122, INV2024140 | P-07 |
| E-08 | Payment released before the goods receipt | INV2024114, INV2024129, INV2024143 | P-10 |
| E-09 | Invoice dated before the goods were received | INV2024004, INV2024114, INV2024129, INV2024143 | P-14 |
| E-10 | Invoice dated before its PO | INV2024004 | P-12 |
| E-11 | Invoice received before its own invoice date | INV2024118, INV2024136 | P-13 |
| E-12 | Vendor not Active, yet ordered from and paid | INV2024126, INV2024150 | P-05 |
| E-13 | Unit price 37.5 times every other order for the item | PO2024127 | P-11 |
| E-14 | Approved requisition never ordered and never withdrawn | REQ2024124, REQ2024138, REQ2024153 | P-04 |
| E-15 | Chain 2024127 passes three controls it should have failed: two approvals above limit and the price outlier | REQ/PO/INV2024127 | P-02, P-09, P-11 |

### What the data cannot answer

| Ref | Question with no field to answer it |
| --- | --- |
| L-01 | Was what arrived what was ordered? (no received quantity) |
| L-02 | Was what was paid what was invoiced? (no payment amount or reference) |
| L-03 | Who raised the PO, and who keyed the invoice? |
| L-04 | When did a vendor's status change? (current status only; no bank, tax or onboarding details) |
| L-05 | Which approval limit applied on the day? (no effective dates) |
| L-06 | Was a requisition withdrawn? (status has only Approved and Completed) |

### Implications for the plan

| Ref | The memo concludes |
| --- | --- |
| I-01 | Test the 18 requisitions over 10M individually; cover the other 37 with population rules. |
| I-02 | Test the payment release step on every invoice: receipt link, approval, amount, date. |
| I-03 | Obtain the evidence behind the CEO's approvals: 16 invoices, 495M. |
| I-04 | Corroborate the dates behind every timing exception before relying on them. |
| I-05 | Drop "PO within estimate" as a test. |
