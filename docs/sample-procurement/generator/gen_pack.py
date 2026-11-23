"""Generate sample pack 02 (REQ2024105 / PO2024105 / GRN2024105 / INV2024105).

The five documents copy the layout of pack 01: native PDFs for the requisition,
purchase order and invoice; a cream "controlled form" goods receipt note and
payment voucher with signature lines and a stamp. Unlike pack 01, whose GRN and
voucher are scans with an OCR text layer, every field here, signatures included,
is real text, so a run that reads text can reach everything on the page.

Every value matches the Excel population except one, deliberately: the GRN
records 17 laptops received against 20 ordered, invoiced and paid (D-05).

It also rebuilds three of pack 01's documents, field for field and signature
for signature. The purchase order loses the "Mock audit evidence" footer its
original carried: no document in the pack may tell a reader that it is not real
evidence. The goods receipt note and payment voucher were scans whose OCR text
layer dropped the handwritten signatures and the RECEIVED stamp and garbled the
rest, which led runs to report the vendor's representative as the receiver.
Rebuilt, every word a reader sees is in the text.

Each document is written as HTML and printed to PDF by headless Microsoft Edge,
so nothing beyond the Python standard library and Edge is needed.

Usage (from the repository root):

    .venv\\Scripts\\python.exe docs\\sample-procurement\\generator\\gen_pack.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "documents" / "samples" / "02_REQ2024105_PO2024105_INV2024105"
EDGE_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

# --------------------------------------------------------------------------- data
# Taken from the Excel rows for this chain. Only GRN_QUANTITY departs from them.
VENDOR = "Vertex IT Hardware"
VENDOR_ID = "V1034"
VENDOR_ADDRESS = "Office 4, 2nd Floor, Saeed Plaza, Blue Area, Islamabad, Pakistan"
VENDOR_CONTACT = "Usman Tariq"
VENDOR_BANK = "Meezan Bank / 0102457736"
ITEM = "Laptop refresh — branch staff"
ORDERED = 20
UNIT_PRICE = 145_000
TOTAL = ORDERED * UNIT_PRICE  # 2,900,000, as on the requisition, PO and invoice
GRN_QUANTITY = 17  # the planted discrepancy: three laptops short


def pkr(value: int) -> str:
    return f"{value:,.2f}"


# --------------------------------------------------------------------------- styles
BASE = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { width: 210mm; height: 297mm; font-family: Arial, Helvetica, sans-serif;
       color: #222; -webkit-print-color-adjust: exact; print-color-adjust: exact;
       position: relative; overflow: hidden; display: flow-root; }
.sig { font-family: 'Segoe Script', 'Segoe Print', 'Ink Free', cursive;
       color: #1d3a6e; font-size: 15pt; }
"""

RECORD = BASE + """
.band { background: #1c4a72; color: #fff; padding: 9mm 14mm 6mm; }
.band .t1 { font-size: 20pt; font-weight: bold; }
.band .t2 { font-size: 16pt; font-weight: bold; margin-top: 2mm; }
.band .ref { font-size: 9pt; margin-top: 2mm; }
.band .right { position: absolute; right: 18mm; top: 11mm; font-size: 8.5pt; font-weight: bold; }
.wrap { padding: 8mm 13mm 0; }
.sec { border: 1px solid #1c4a72; background: #e1ecf6; color: #1c4a72; font-weight: bold;
       font-size: 10.5pt; padding: 2.5mm 3mm; margin-top: 4mm; }
table { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
td { padding: 2.6mm 2mm; border-bottom: 1px solid #ddd; vertical-align: top; }
td.k { width: 50mm; color: #555; font-weight: bold; font-size: 8.5pt; }
.foot { position: absolute; bottom: 14mm; left: 0; right: 0; text-align: center;
        font-size: 7.5pt; color: #555; }
"""

COMMERCIAL = BASE + """
.band { background: #163a63; color: #fff; padding: 9mm 14mm 7mm; }
.band .t1 { font-size: 19pt; }
.band .ref { font-size: 9.5pt; margin-top: 3mm; color: #dce6f2; }
.wrap { padding: 4mm 13mm 0; }
.sec { background: #e6eff8; color: #163a63; font-weight: bold; font-size: 11pt;
       padding: 2.2mm 3mm; margin-top: 3mm; }
table { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin: 1mm 0 1mm 0; }
td { padding: 1.6mm 4mm; vertical-align: top; }
td.k { width: 60mm; font-weight: bold; color: #333; }
.foot { position: absolute; bottom: 14mm; left: 13mm; right: 13mm; border-top: 1px solid #bbb;
        padding-top: 4mm; font-size: 8pt; color: #555; }
"""

PAPER = BASE + """
body { background: #f4efe4; }
"""

GRN = PAPER + """
.head { margin: 9mm 10mm 0; border: 1.5px solid #1c4a72; padding: 5mm 4mm; position: relative; }
.head .t1 { font-size: 19pt; font-weight: bold; color: #1c4a72; }
.head .t2 { font-size: 12pt; font-weight: bold; margin-top: 1mm; }
.head .right { position: absolute; right: 13mm; top: 6mm; font-size: 8.5pt; color: #555; }
table { margin: 8mm 11mm 0; width: calc(100% - 22mm); border-collapse: collapse; font-size: 10.5pt; }
td { border: 1px solid #888; padding: 2.6mm 3mm 2.6mm 5mm; }
td.k { width: 50mm; padding-left: 3mm; background: #dde6ee; font-weight: bold; color: #1c3a5a; }
.auth { position: absolute; top: 205mm; left: 11mm; right: 11mm; }
.auth .h { font-weight: bold; color: #1c4a72; font-size: 11pt; margin-bottom: 9mm; }
.cols { display: flex; gap: 6mm; }
.col { flex: 1; }
.line { border-bottom: 1px solid #555; height: 11mm; padding-left: 2mm; display: flex; align-items: flex-end; padding-bottom: 1mm; }
.cap { font-size: 8.5pt; color: #444; margin-top: 2mm; }
.stamp { position: absolute; right: 19mm; bottom: 15mm; width: 31mm; height: 31mm; border-radius: 50%;
         border: 2.5px solid #a3302a; display: flex; align-items: center; justify-content: center;
         color: #a3302a; font-weight: bold; font-size: 11pt; box-shadow: inset 0 0 0 2mm #f4efe4, inset 0 0 0 2.4mm #a3302a; }
"""

VOUCHER = PAPER + """
.frame { position: absolute; left: 9mm; right: 9mm; top: 9mm; bottom: 9mm; border: 1.5px solid #4a5a6a; }
.band { background: #1b3a5c; color: #fff; padding: 5mm 6mm 4mm; }
.band .t1 { font-size: 21pt; font-weight: bold; }
.band .ref { font-size: 9pt; margin-top: 1mm; color: #dce6f2; }
table { margin: 6mm 5mm 0; width: calc(100% - 10mm); border-collapse: collapse; font-size: 12pt; }
td { padding: 3mm 1mm; border-bottom: 1px solid #b8b4aa; }
td.k { width: 75mm; font-weight: bold; color: #2a3a4a; }
.auth { position: absolute; top: 183mm; left: 7mm; }
.auth .h { font-weight: bold; font-size: 12pt; color: #2a3a4a; margin-bottom: 6mm; }
.cols { display: flex; gap: 12mm; }
.line { border-bottom: 1px solid #333; width: 42mm; height: 10mm; padding-left: 2mm; display: flex; align-items: flex-end; padding-bottom: 1mm; }
.cap { font-size: 9pt; color: #444; margin-top: 1mm; }
.stamp { position: absolute; right: 9mm; bottom: 14mm; width: 42mm; height: 34mm; border-radius: 50%;
         border: 3px solid #a3302a; color: #a3302a; font-weight: bold; font-size: 12pt;
         display: flex; align-items: flex-start; justify-content: flex-start; padding: 9mm 0 0 8mm; }
.foot { position: absolute; bottom: 2mm; left: 5mm; font-size: 8pt; color: #555; }
"""


def rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(f'<tr><td class="k">{k}</td><td>{v}</td></tr>' for k, v in pairs)


def page(title: str, css: str, body: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head><body>{body}</body></html>'


# --------------------------------------------------------------------------- documents
def requisition() -> str:
    body = f"""
<div class="band"><div class="t1">GLOBAL BANK</div><div class="t2">PURCHASE REQUISITION</div>
<div class="ref">REQ2024105</div><div class="right">PROCUREMENT RECORD</div></div>
<div class="wrap">
<div class="sec">REQUISITION DETAILS</div>
<table>{rows([
    ("Requisition ID", "REQ2024105"),
    ("Requisition date", "01-Oct-2024"),
    ("Requesting department", "Human Resources"),
    ("Requested by", "Hina Raza (1056)"),
    ("Proposed vendor", f"{VENDOR} ({VENDOR_ID})"),
    ("Business requirement", "Replacement of end-of-life laptops issued to branch staff, to support the branch expansion programme."),
])}</table>
<div class="sec">ITEM AND VALUE</div>
<table>{rows([
    ("Description", ITEM),
    ("Quantity", f"{ORDERED} Laptops"),
    ("Estimated unit cost (PKR)", pkr(UNIT_PRICE)),
    ("Estimated total cost (PKR)", pkr(TOTAL)),
    ("Status", "Completed"),
])}</table>
<div class="sec">WORKFLOW APPROVALS</div>
<table>{rows([
    ("Verified by", "Omar Farooq (1013) on 02-Oct-2024"),
    ("Procurement approval", "Nadia Hussain (1024) on 03-Oct-2024"),
    ("Financial approval", "Daniel Reed (1003) on 04-Oct-2024"),
])}</table>
</div>
<div class="foot">Confidential procurement record. Amounts are stated in full PKR unless otherwise indicated.</div>"""
    return page("REQ2024105 Purchase Requisition", RECORD, body)


def _purchase_order(
    *, number: str, date: str, requisition: str, vendor: str, address: str,
    contact: str, item: str, quantity: int, unit_price: int, grn: str, grn_date: str,
) -> str:
    body = f"""
<div class="band"><div class="t1">PURCHASE ORDER</div><div class="ref">Order reference: {number}</div></div>
<div class="wrap">
<div class="sec">Order details</div>
<table>{rows([("PO date", date), ("Requisition", requisition), ("Status", "Closed")])}</table>
<div class="sec">Supplier</div>
<table>{rows([("Vendor", vendor), ("Address", address), ("Contact", contact)])}</table>
<div class="sec">Commercial terms</div>
<table>{rows([
    ("Description", item),
    ("Quantity", str(quantity)),
    ("Unit price (PKR)", f"PKR {pkr(unit_price)}"),
    ("PO total (PKR)", f"PKR {pkr(quantity * unit_price)}"),
])}</table>
<div class="sec">Control references</div>
<table>{rows([("Buyer", "B001"), ("GRN", grn), ("GRN date", grn_date)])}</table>
</div>
<div class="foot">All monetary values are presented in full PKR.</div>"""
    return page(f"{number} Purchase Order", COMMERCIAL, body)


def purchase_order() -> str:
    return _purchase_order(
        number="PO2024105", date="14 Oct 2024", requisition="REQ2024105",
        vendor=f"{VENDOR} ({VENDOR_ID})", address=VENDOR_ADDRESS, contact=VENDOR_CONTACT,
        item=ITEM, quantity=ORDERED, unit_price=UNIT_PRICE,
        grn="GRN2024105", grn_date="26 Oct 2024",
    )


def pack01_purchase_order() -> str:
    """Pack 01's PO2024004, field for field, without its "Mock audit evidence" footer."""
    return _purchase_order(
        number="PO2024004", date="19 Apr 2024", requisition="REQ2024009",
        vendor="OfficeSupply Co. (V1022)",
        address="Plot 18, Block A, Gulshan-e-Iqbal, Karachi, Pakistan", contact="Ahmed Khan",
        item="New Hire Onboarding Kits", quantity=25, unit_price=80_000,
        grn="GRN2024004", grn_date="29 Apr 2024",
    )


def _goods_receipt(
    *, number: str, order: str, vendor: str, date: str, item: str, quantity: int,
    comments: str, received_by: str, vendor_signatory: str,
) -> str:
    body = f"""
<div class="head"><div class="t1">GLOBAL BANK</div><div class="t2">GOODS RECEIPT NOTE</div>
<div class="right">CONTROLLED FORM</div></div>
<table>{rows([
    ("GRN / receipt number", number),
    ("Purchase order", order),
    ("Vendor", vendor),
    ("Receipt date", date),
    ("Description", item),
    ("Quantity received", str(quantity)),
    ("Receipt status", "Received"),
    ("Inspection comments", comments),
])}</table>
<div class="auth"><div class="h">AUTHORIZATION / ACKNOWLEDGEMENT</div>
<div class="cols">
<div class="col"><div class="line"><span class="sig">{received_by}</span></div><div class="cap">Received and inspected by</div></div>
<div class="col"><div class="line"><span class="sig">{vendor_signatory}</span></div><div class="cap">Vendor representative</div></div>
</div></div>
<div class="stamp">RECEIVED</div>"""
    return page(f"{number} Goods Receipt Note", GRN, body)


def goods_receipt() -> str:
    return _goods_receipt(
        number="GRN2024105", order="PO2024105", vendor=f"{VENDOR} ({VENDOR_ID})",
        date="26-Oct-2024", item=ITEM, quantity=GRN_QUANTITY,
        comments="Laptops received and inspected.",
        received_by="Hina Raza (1056)", vendor_signatory=VENDOR_CONTACT,
    )


def pack01_goods_receipt() -> str:
    """Pack 01's GRN2024004, as the scan shows it, with every word real text."""
    return _goods_receipt(
        number="GRN2024004", order="PO2024004", vendor="OfficeSupply Co. (V1022)",
        date="29-Apr-2024", item="New Hire Onboarding Kits", quantity=25,
        comments="All kits delivered.",
        received_by="Ethan Smith (1041)", vendor_signatory="Ahmed Khan",
    )


def invoice() -> str:
    body = f"""
<div class="band"><div class="t1">TAX INVOICE</div><div class="ref">Vendor invoice: VINV105-2024</div></div>
<div class="wrap">
<div class="sec">Supplier</div>
<table>{rows([("Vendor", VENDOR), ("Vendor reference", VENDOR_ID), ("Address", VENDOR_ADDRESS), ("Bank", VENDOR_BANK)])}</table>
<div class="sec">Invoice details</div>
<table>{rows([
    ("Internal invoice ID", "INV2024105"),
    ("Invoice date", "01 Nov 2024"),
    ("Date received", "05 Nov 2024"),
    ("Purchase reference", "PO2024105"),
    ("GRN reference", "GRN2024105"),
])}</table>
<div class="sec">Charges</div>
<table>{rows([("Description", ITEM), ("Invoice amount (PKR)", f"PKR {pkr(TOTAL)}"), ("Due date", "01 Dec 2024")])}</table>
</div>
<div class="foot">All monetary values are presented in full PKR.</div>"""
    return page("VINV105-2024 Invoice", COMMERCIAL, body)


def _payment_voucher(
    *, reference: str, vendor: str, vendor_invoice: str, order: str, amount: int,
    date: str, signatories: tuple[str, str],
) -> str:
    body = f"""
<div class="frame">
<div class="band"><div class="t1">PAYMENT VOUCHER</div><div class="ref">Voucher reference: {reference}</div></div>
<table>{rows([
    ("Vendor", vendor),
    ("Vendor invoice", vendor_invoice),
    ("Purchase reference", order),
    ("Payment amount (PKR)", f"PKR {pkr(amount)}"),
    ("Payment status", "Paid"),
    ("Payment date", date),
])}</table>
<div class="auth"><div class="h">Authorisations</div>
<div class="cols">
<div><div class="line"><span class="sig">{signatories[0]}</span></div><div class="cap">Signed</div></div>
<div><div class="line"><span class="sig">{signatories[1]}</span></div><div class="cap">Signed</div></div>
</div></div>
<div class="stamp">PAID</div>
<div class="foot">Amounts are in full PKR</div>
</div>"""
    return page(f"{reference} Payment Voucher", VOUCHER, body)


def payment_voucher() -> str:
    return _payment_voucher(
        reference="INV2024105", vendor=f"{VENDOR} ({VENDOR_ID})", vendor_invoice="VINV105-2024",
        order="PO2024105", amount=TOTAL, date="20 Nov 2024",
        signatories=("Omar Farooq", "Daniel Reed"),
    )


def pack01_payment_voucher() -> str:
    """Pack 01's voucher for INV2024004, as the scan shows it, with every word real text."""
    return _payment_voucher(
        reference="INV2024004", vendor="OfficeSupply Co. (V1022)", vendor_invoice="VINV001-202404",
        order="PO2024004", amount=2_000_000, date="01 May 2024",
        signatories=("Olivia Smith", "Max Baker"),
    )


PACK01 = ROOT / "documents" / "samples" / "01_REQ2024009_PO2024004_INV2024004"

DOCUMENTS = {
    OUT / "REQ2024105_Purchase_Requisition.pdf": requisition,
    OUT / "PO2024105_Purchase_Order.pdf": purchase_order,
    OUT / "GRN2024105_Signed_Receipt.pdf": goods_receipt,
    OUT / "VINV105-2024_Invoice.pdf": invoice,
    OUT / "INV2024105_Signed_Payment_Voucher.pdf": payment_voucher,
    # Pack 01, rebuilt. The PO drops a footer that told a reader the evidence
    # was a mock. The GRN and voucher replace scans whose OCR text layer lost
    # the handwritten signatures and the RECEIVED stamp and garbled the rest.
    PACK01 / "PO2024004_Purchase_Order.pdf": pack01_purchase_order,
    PACK01 / "GRN2024004_Signed_Receipt.pdf": pack01_goods_receipt,
    PACK01 / "INV2024004_Signed_Payment_Voucher.pdf": pack01_payment_voucher,
}


def main() -> None:
    edge = next((path for path in EDGE_CANDIDATES if path.exists()), None)
    if edge is None:
        raise SystemExit("Microsoft Edge was not found; it prints the HTML to PDF.")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for target, build in DOCUMENTS.items():
            html = Path(tmp) / (target.stem + ".html")
            html.write_text(build(), encoding="utf-8")
            subprocess.run(
                [
                    str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={Path(tmp) / 'edge-profile'}",
                    f"--print-to-pdf={target}", html.as_uri(),
                ],
                check=True, capture_output=True, timeout=120,
            )
            print("wrote", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
