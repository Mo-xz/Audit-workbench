"""Rebuild the procurement EDA benchmark memo from the pack's own workbooks.

Every figure in ``memo.html`` is computed here, locally, in Polars, from
``docs/sample-procurement/data``. The script writes ``data.json`` (the exhibit
data) and fills ``memo.template.html`` with it to produce ``memo.html``.

    uv run --no-project python docs/sample-procurement/eda-benchmark/build_memo.py
"""
import datetime as _dt
import json
from pathlib import Path

import polars as pl

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
req = pl.read_excel(DATA / "Requisitions.xlsx")
po = pl.read_excel(DATA / "PO Data.xlsx")
inv = pl.read_excel(DATA / "Invoice data.xlsx")
staff = pl.read_excel(DATA / "Staff Details.xlsx")
ven = pl.read_excel(DATA / "Vendor Master File.xlsx")
mat = pl.read_excel(DATA / "Financial approval matrix.xlsx")

out = {}
d = lambda a, b: (pl.col(b) - pl.col(a)).dt.total_days()
s = staff.select('STAFF_ID', 'NAME', 'JOB_TITLE')
chain = (req.join(po.drop('VENDOR_ID'), on='REQUISITION_ID', how='inner')
            .join(inv.rename({'VERIFIED_BY_ID': 'INV_VERIFIED_BY_ID', 'VENDOR_ID': 'INV_VENDOR_ID'}),
                  left_on='PO_NUMBER', right_on='PO_NUMBER_LINK', how='inner')
            .join(ven, left_on='VENDOR_ID', right_on='VENDOR_ID', how='left'))
out['population'] = dict(
    req_n=req.height, req_v=int(req['ESTIMATED_TOTAL_COST'].sum()),
    po_n=po.height, po_v=int(po['PO_TOTAL_AMOUNT'].sum()),
    grn_n=int(po['GRN_ID'].is_not_null().sum()),
    inv_n=inv.height, inv_v=int(inv['INVOICE_AMOUNT'].sum()),
    paid_n=int((inv['PAYMENT_STATUS'] == 'Paid').sum()),
    staff=staff.height, vendors=ven.height, matrix=mat.height,
    req_from=str(req['REQUISITION_DATE'].min()), req_to=str(req['REQUISITION_DATE'].max()),
    po_to=str(po['PO_DATE'].max()), inv_to=str(inv['INVOICE_DATE'].max()), pay_to=str(inv['PAYMENT_DATE'].max()),
    po_eq_est=int((chain['PO_TOTAL_AMOUNT'] == chain['ESTIMATED_TOTAL_COST']).sum()),
    inv_eq_po=int((chain['INVOICE_AMOUNT'] == chain['PO_TOTAL_AMOUNT']).sum()),
    same_verifier=int((chain['VERIFIED_BY_ID'] == chain['INV_VERIFIED_BY_ID']).sum()),
)
# monthly committed vs paid
months = pl.date_range(pl.date(2024, 1, 1), pl.date(2025, 2, 1), '1mo', eager=True).alias('m').to_frame()
committed = po.group_by(pl.col('PO_DATE').dt.truncate('1mo').alias('m')).agg(pl.col('PO_TOTAL_AMOUNT').sum().alias('committed'), pl.len().alias('pos'))
paid = inv.group_by(pl.col('PAYMENT_DATE').dt.truncate('1mo').alias('m')).agg(pl.col('INVOICE_AMOUNT').sum().alias('paid'), pl.len().alias('payments'))
monthly = months.join(committed, on='m', how='left').join(paid, on='m', how='left').fill_null(0).sort('m')
out['monthly'] = [dict(m=str(r['m'])[:7], committed=r['committed'], pos=r['pos'], paid=r['paid'], payments=r['payments']) for r in monthly.iter_rows(named=True)]
# size bands
bands = (req.with_columns(pl.col('ESTIMATED_TOTAL_COST').cut([1_000_000, 5_000_000, 10_000_000, 50_000_000],
          labels=['Up to 1M', '1M to 5M', '5M to 10M', '10M to 50M', 'Over 50M']).alias('band'))
          .group_by('band').agg(pl.len().alias('n'), pl.col('ESTIMATED_TOTAL_COST').sum().alias('v')).sort('band'))
out['bands'] = [dict(band=str(r['band']), n=r['n'], v=r['v']) for r in bands.iter_rows(named=True)]
# departments
dep = (req.join(s, left_on='REQUESTER_ID', right_on='STAFF_ID', how='left')
       .group_by('REQUESTER_DEPARTMENT').agg(pl.len().alias('n'), pl.col('ESTIMATED_TOTAL_COST').sum().alias('v'),
        pl.col('NAME').unique().sort().alias('requesters'), pl.col('ESTIMATED_TOTAL_COST').max().alias('max'))
       .sort('v', descending=True))
out['departments'] = [dict(dept=r['REQUESTER_DEPARTMENT'], n=r['n'], v=r['v'], requesters=r['requesters'], max=r['max']) for r in dep.iter_rows(named=True)]
# vendors
vd = (chain.group_by('INV_VENDOR_ID', 'VENDOR_NAME', 'VENDOR_STATUS')
      .agg(pl.len().alias('n'), pl.col('INVOICE_AMOUNT').sum().alias('v'), pl.col('ITEM_DESCRIPTION').n_unique().alias('items'),
           pl.col('INVOICE_ID').sort().alias('invoices'))
      .sort('v', descending=True))
out['vendors'] = [dict(id=r['INV_VENDOR_ID'], name=r['VENDOR_NAME'], status=r['VENDOR_STATUS'], n=r['n'], v=r['v'], items=r['items'], invoices=r['invoices']) for r in vd.iter_rows(named=True)]
# department x item
di = chain.group_by('REQUESTER_DEPARTMENT', 'ITEM_DESCRIPTION').agg(pl.len().alias('n'), pl.col('INVOICE_AMOUNT').sum().alias('v')).sort('REQUESTER_DEPARTMENT', 'ITEM_DESCRIPTION')
out['dept_item'] = [dict(dept=r['REQUESTER_DEPARTMENT'], item=r['ITEM_DESCRIPTION'], n=r['n'], v=r['v']) for r in di.iter_rows(named=True)]
it = po.group_by('ITEM_DESCRIPTION').agg(pl.col('PO_TOTAL_AMOUNT').sum().alias('v')).sort('v', descending=True)
out['items_order'] = it['ITEM_DESCRIPTION'].to_list()
# unit prices
up = po.with_columns((pl.col('PO_TOTAL_AMOUNT') / pl.col('ORDERED_QUANTITY')).alias('unit')).select('PO_NUMBER', 'ITEM_DESCRIPTION', 'VENDOR_ID', 'ORDERED_QUANTITY', 'PO_TOTAL_AMOUNT', 'unit')
out['unit_prices'] = up.to_dicts()
# cycle times
stages = [('REQUISITION_DATE', 'VERIFIED_DATE', 'Requisition verified'), ('VERIFIED_DATE', 'APPROVAL_DATE', 'Procurement approval'),
          ('APPROVAL_DATE', 'FIN_APPROVAL_DATE', 'Financial approval'), ('FIN_APPROVAL_DATE', 'PO_DATE', 'PO raised'),
          ('PO_DATE', 'GRN_DATE', 'Goods received'), ('GRN_DATE', 'INVOICE_DATE', 'Invoice dated'),
          ('INVOICE_DATE', 'DATE_RECEIVED', 'Invoice received'), ('DATE_RECEIVED', 'VERIFICATION_DATE', 'Invoice verified'),
          ('VERIFICATION_DATE', 'SUPERVISOR_APPROVAL_DATE', 'Invoice approved'), ('SUPERVISOR_APPROVAL_DATE', 'PAYMENT_DATE', 'Paid')]
cyc = []
for a, b, label in stages:
    x = chain.select(d(a, b).alias('x')).drop_nulls()['x']
    cyc.append(dict(stage=label, frm=a, to=b, n=x.len(), min=int(x.min()), p25=float(x.quantile(0.25, 'nearest')), med=float(x.median()), p75=float(x.quantile(0.75, 'nearest')), max=int(x.max()), neg=int((x < 0).sum())))
out['cycle'] = cyc
e2e = chain.select(d('REQUISITION_DATE', 'PAYMENT_DATE').alias('x'))['x']
out['e2e'] = dict(min=int(e2e.min()), med=float(e2e.median()), max=int(e2e.max()))
# payment vs due
early = chain.select((-d('DUE_DATE', 'PAYMENT_DATE')).alias('early'), 'INVOICE_AMOUNT', 'INVOICE_ID')
hist = early.group_by(((pl.col('early') // 3) * 3).alias('bin')).agg(pl.len().alias('n'), pl.col('INVOICE_AMOUNT').sum().alias('v')).sort('bin')
out['early'] = dict(all_early=int((early['early'] > 0).sum()), median=float(early['early'].median()), min=int(early['early'].min()), max=int(early['early'].max()),
                    terms=int(chain.select(d('INVOICE_DATE', 'DUE_DATE').alias('t'))['t'].median()),
                    hist=[dict(bin=int(r['bin']), n=r['n'], v=r['v']) for r in hist.iter_rows(named=True)])
# approval routing
band_expr = lambda col: (pl.when(pl.col(col) <= 1_000_000).then(pl.lit('Up to 1M')).when(pl.col(col) <= 5_000_000).then(pl.lit('1M to 5M'))
                         .when(pl.col(col) <= 10_000_000).then(pl.lit('5M to 10M')).otherwise(pl.lit('Over 10M')))
def routing(df, who, amt, idcol):
    r = (df.join(s, left_on=who, right_on='STAFF_ID', how='left').join(mat, on='JOB_TITLE', how='left')
         .with_columns(band_expr(amt).alias('band'), pl.col('JOB_TITLE').fill_null('No approver recorded')))
    g = r.group_by('band', 'JOB_TITLE').agg(pl.len().alias('n'), pl.col(amt).sum().alias('v'),
          (pl.col(amt) > pl.col('MAX_APPROVAL_AMOUNT')).sum().alias('over'), pl.col(idcol).sort().alias('ids')).sort('band', 'JOB_TITLE')
    return [dict(band=x['band'], title=x['JOB_TITLE'], n=x['n'], v=x['v'], over=x['over'], ids=x['ids']) for x in g.iter_rows(named=True)]
out['routing_req'] = routing(req, 'FIN_APPROVED_BY_ID', 'ESTIMATED_TOTAL_COST', 'REQUISITION_ID')
out['routing_inv'] = routing(inv, 'SUPERVISOR_APPROVAL_ID', 'INVOICE_AMOUNT', 'INVOICE_ID')
out['matrix'] = mat.to_dicts()
ceo_req = req.filter(pl.col('FIN_APPROVED_BY_ID') == 1001)['ESTIMATED_TOTAL_COST'].sum()
ceo_inv = inv.filter(pl.col('SUPERVISOR_APPROVAL_ID') == 1001)['INVOICE_AMOUNT'].sum()
out['ceo'] = dict(req_n=int((req['FIN_APPROVED_BY_ID'] == 1001).sum()), req_v=int(ceo_req), inv_n=int((inv['SUPERVISOR_APPROVAL_ID'] == 1001).sum()), inv_v=int(ceo_inv))
# roles matrix
roles = [('Raised requisition', req, 'REQUESTER_ID'), ('Verified requisition', req, 'VERIFIED_BY_ID'), ('Procurement approval', req, 'APPROVED_BY_ID'),
         ('Financial approval', req, 'FIN_APPROVED_BY_ID'), ('Verified invoice', inv, 'VERIFIED_BY_ID'), ('Approved invoice', inv, 'SUPERVISOR_APPROVAL_ID')]
rm = []
for label, df, col in roles:
    for r in df.group_by(col).len().drop_nulls().sort(col).iter_rows(named=True):
        rm.append(dict(role=label, staff=r[col], n=r['len']))
out['roles'] = rm
out['roles_order'] = [r[0] for r in roles]
out['staff'] = staff.join(mat, on='JOB_TITLE', how='left').to_dicts()
# weekends
dates = [('REQUISITION_DATE', 'Requisition'), ('VERIFIED_DATE', 'Requisition verified'), ('APPROVAL_DATE', 'Procurement approval'),
         ('FIN_APPROVAL_DATE', 'Financial approval'), ('PO_DATE', 'PO'), ('GRN_DATE', 'Goods receipt'), ('INVOICE_DATE', 'Invoice date'),
         ('DATE_RECEIVED', 'Invoice received'), ('VERIFICATION_DATE', 'Invoice verified'), ('SUPERVISOR_APPROVAL_DATE', 'Invoice approved'), ('PAYMENT_DATE', 'Payment')]
wk = []
for col, label in dates:
    x = chain[col].drop_nulls()
    wk.append(dict(field=label, col=col, n=x.len(), weekend=int((x.dt.weekday() >= 6).sum())))
out['weekend'] = wk
# exceptions
E = []
def add(theme, title, df, idcol, amtcol, note, exhibit):
    E.append(dict(theme=theme, title=title, records=df[idcol].to_list(), n=df.height, value=int(df[amtcol].sum()), note=note, exhibit=exhibit))
fa = req.join(s, left_on='FIN_APPROVED_BY_ID', right_on='STAFF_ID').join(mat, on='JOB_TITLE').filter(pl.col('ESTIMATED_TOTAL_COST') > pl.col('MAX_APPROVAL_AMOUNT'))
ia = inv.join(s, left_on='SUPERVISOR_APPROVAL_ID', right_on='STAFF_ID').join(mat, on='JOB_TITLE').filter(pl.col('INVOICE_AMOUNT') > pl.col('MAX_APPROVAL_AMOUNT'))
out['breaches'] = dict(req=fa.select('REQUISITION_ID', 'ESTIMATED_TOTAL_COST', 'NAME', 'JOB_TITLE', 'MAX_APPROVAL_AMOUNT').to_dicts(),
                       inv=ia.select('INVOICE_ID', 'INVOICE_AMOUNT', 'NAME', 'JOB_TITLE', 'MAX_APPROVAL_AMOUNT').to_dicts())
add('Authority', 'Requisition financially approved above the approver\'s limit', fa, 'REQUISITION_ID', 'ESTIMATED_TOTAL_COST', 'Head of Treasury (limit 1M) approved 4.2M and 3.0M; the CFO (limit 10M) approved 64M.', 'routing')
add('Authority', 'Invoice approved above the approver\'s limit', ia, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Both approved by the Head of Treasury, limit 1M.', 'routing')
x = req.filter(pl.col('APPROVED_BY_ID').is_null()); add('Approval', 'Procurement approval not recorded, requisition completed and ordered', x, 'REQUISITION_ID', 'ESTIMATED_TOTAL_COST', 'Approver and approval date both blank; all three went on to financial approval and a PO.', 'roles')
x = inv.filter(pl.col('SUPERVISOR_APPROVAL_ID').is_null()); add('Approval', 'Invoice paid with no approval recorded', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Approver and approval date both blank; all three paid.', 'routing')
x = req.filter(pl.col('VERIFIED_BY_ID') == pl.col('REQUESTER_ID')); add('Segregation', 'Requisition verified by the person who raised it', x, 'REQUISITION_ID', 'ESTIMATED_TOTAL_COST', 'Every other requisition is verified by Finance; here the requester took the Finance step.', 'roles')
x = inv.filter(pl.col('GRN_ID_LINK').is_null()); add('Matching', 'Invoice paid with no goods receipt reference', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Each PO does carry a GRN, so the goods may have arrived; the invoice was paid without being matched to it.', 'chain')
x = chain.filter(pl.col('INVOICE_AMOUNT') > pl.col('PO_TOTAL_AMOUNT')).with_columns((pl.col('INVOICE_AMOUNT') - pl.col('PO_TOTAL_AMOUNT')).alias('excess'))
add('Matching', 'Invoice amount above the PO total (value shown is the excess)', x, 'INVOICE_ID', 'excess', 'Excess of 11.2M (35%), 1.3M (140%) and 37,800 (18%). Every other invoice equals its PO exactly.', 'chain')
x = chain.filter(pl.col('PAYMENT_DATE') < pl.col('GRN_DATE')); add('Timing', 'Payment released before the goods receipt', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Paid 8, 13 and 9 days before the GRN date.', 'cycle')
x = chain.filter(pl.col('INVOICE_DATE') < pl.col('GRN_DATE')); add('Timing', 'Invoice dated before the goods were received', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Billing in advance of delivery; three of the four are also the payments above.', 'cycle')
x = chain.filter(pl.col('INVOICE_DATE') < pl.col('PO_DATE')); add('Timing', 'Invoice dated before its purchase order', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Dated 9 April against a PO of 19 April; the same chain sits outside every numbering series.', 'chain')
x = chain.filter(pl.col('DATE_RECEIVED') < pl.col('INVOICE_DATE')); add('Timing', 'Invoice recorded as received before its own invoice date', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'Received 2 and 3 days before the date printed on the invoice.', 'cycle')
x = chain.filter(pl.col('VENDOR_STATUS') != 'Active'); add('Master data', 'Vendor not Active, yet ordered from and paid', x, 'INVOICE_ID', 'INVOICE_AMOUNT', 'V1010 is Under Review and V1017 Inactive. The master holds no status-change date.', 'vendors')
x = up.filter((pl.col('ITEM_DESCRIPTION') == 'New Hire Onboarding Kits') & (pl.col('unit') > 100_000)); add('Pricing', 'Unit price far above every other order for the same item', x, 'PO_NUMBER', 'PO_TOTAL_AMOUNT', 'One kit at 3,000,000 against 80,000 on the three other orders, 37.5 times the price.', 'prices')
yearend = _dt.date(2024, 12, 31)
x = req.filter(pl.col('PO_NUMBER').is_null()).with_columns((pl.lit(yearend) - pl.col('FIN_APPROVAL_DATE')).dt.total_days().alias('age'))
out['stale'] = x.select('REQUISITION_ID', 'ESTIMATED_TOTAL_COST', 'FIN_APPROVAL_DATE', 'age').to_dicts()
add('Completeness', 'Approved requisition never ordered and never withdrawn', x, 'REQUISITION_ID', 'ESTIMATED_TOTAL_COST', f"{int(x['age'].min())} to {int(x['age'].max())} days old at year end; every other requisition became a PO within {int(chain.select(d('FIN_APPROVAL_DATE','PO_DATE').alias('x'))['x'].max())} days.", 'cycle')
out['exceptions'] = E
out['fin_to_po_max'] = int(chain.select(d('FIN_APPROVAL_DATE', 'PO_DATE').alias('x'))['x'].max())
# exceptions touching each person (by the role that produced the exception)
data = json.dumps(out, default=str, indent=1)
(HERE / "data.json").write_text(data + "\n")
template = (HERE / "memo.template.html").read_text()
page = template.replace("/*DATA*/", data)
(HERE / "memo.html").write_text(
    '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    + page + "\n</html>\n"
)
