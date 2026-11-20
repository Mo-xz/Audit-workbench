# Procure-to-Pay Audit Demo Pack

This pack is for an internal audit of procure-to-pay at Global Bank, covering
requisitions raised in calendar 2024 and the orders, receipts and payments that
settle them.

It is deliberately small: 55 requisitions, 52 purchase orders and 52 invoices,
with staff, vendor and approval-matrix masters and two fully documented
transactions. It is meant for a fast end-to-end demonstration and for scoring a
run against a known answer key.

## Fast demo setup

1. Create a workspace named **Procurement Audit - 2024**.
2. Import each Excel file from `data/` as a separate table.
3. Add the three DOCX files from `documents/planning/` to the document
   inventory. Then stage the two folders under `documents/samples/`. Each
   holds one sampled transaction, and each PDF in it is one document.
4. In auto mode, use this command:

   `Perform a risk-based internal audit of the procure-to-pay cycle for 2024,
   covering requisition and approval, purchase orders, goods receipt, and
   invoice processing and payment. Assess compliance with the Procurement SOP
   and the Financial Approval Matrix; test approval authority, segregation of
   duties, vendor status, three-way matching and the sequence of approval,
   receipt and payment; identify exceptions; prepare evidence-backed findings
   and a draft report.`

## Contents

- `data/Requisitions.xlsx`: 55 requisitions, PKR 645.4m, with requester,
  verifier, procurement approver and financial approver, each with a date.
- `data/PO Data.xlsx`: 52 purchase orders, PKR 610.0m, each carrying its goods
  receipt (GRN number, date and status).
- `data/Invoice data.xlsx`: 52 invoices, PKR 622.5m, all paid, with
  verification, supervisor approval and payment dates.
- `data/Staff Details.xlsx`: 20 staff with job title and supervisor.
- `data/Vendor Master File.xlsx`: 12 vendors and their status.
- `data/Financial approval matrix.xlsx`: approval limits by job title.
- `documents/planning/Procurement SOP Extracts.docx`: the compliance baseline,
  sections 2 to 5.
- `documents/planning/Financial Approval Matrix.docx`: the approved limits, in PKR.
- `documents/planning/Minutes of Meeting - Procurement Planning.docx`: the
  planning meeting of 22 July 2025, including management's own admissions.
- `documents/samples/01_REQ2024009_PO2024004_INV2024004/` and
  `documents/samples/02_REQ2024105_PO2024105_INV2024105/`: the requisition,
  purchase order, signed goods receipt note, vendor invoice and signed payment
  voucher for one transaction each, as five single-page PDFs. Pack 01's goods
  receipt and voucher are scans; pack 02's five documents are native PDFs.
- `generator/gen_pack.py`: rebuilds pack 02 (and pack 01's purchase order) from
  the values in the tables, printing HTML to PDF with Microsoft Edge.
- `FACILITATOR_GUIDE.md`: the answer key, recommended controls, and how to
  score a run.

## How the tables join

- `Requisitions.REQUISITION_ID` = `PO Data.REQUISITION_ID`, and
  `Requisitions.PO_NUMBER` = `PO Data.PO_NUMBER`.
- `Invoice data.PO_NUMBER_LINK` = `PO Data.PO_NUMBER`, and
  `Invoice data.GRN_ID_LINK` = `PO Data.GRN_ID`.
- Every `*_ID` that names a person (requester, verifier, approvers, supervisor)
  resolves to `Staff Details.STAFF_ID`.
- `Staff Details.JOB_TITLE` = `Financial approval matrix.JOB_TITLE` gives an
  approver's limit. Only four titles have one.
- `VENDOR_ID` on every transaction table resolves to `Vendor Master File`.

## What the sample is built to demonstrate

Exceptions fall into three classes, and the split is deliberate:

1. **Visible in the tables.** These are approval-limit breaches,
   self-verification, unrecorded approvals, inactive vendors, unmatched and
   over-billed invoices, payment before receipt, and one wildly overpriced
   order. The analytics find them without any document. Several need two joins
   to see: an approver's limit is only reachable through the staff file.
2. **Visible only in the documents.** A goods receipt short by three laptops
   that were invoiced and paid in full, goods received by the same associate
   who raised the requisition, a payment authorised by someone with no
   financial authority, and a buyer code that matches no staff record. These
   need the sample packs. Pack 01's signed documents are scans whose
   handwritten signatures are missing from the OCR text layer, so they can only
   be read from the page image. Pack 02 is entirely text, so its short receipt
   can be found by reading alone.
3. **Judgement.** Matters that need inquiry, not a conclusion, such as the
   same branch fit-out ordered three times from different vendors.

The answer key also lists what was tested and found clean, so a run can be
scored for false positives as well as misses.
