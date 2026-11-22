import type { CycleVouchGridPayload } from '../../types'

export type CycleVouchGridColumn = CycleVouchGridPayload['columns'][number]

/**
 * Organizes a Cycle Vouch grid's assertion columns into:
 *   1. Chronological document stages (e.g. Purchase Order -> Goods Receipt ->
 *      Vendor Invoice -> Payment Voucher), derived from the ruleset's ordered
 *      roles when present or inferred cleanly from `applicable_roles`.
 *   2. A test-focused subset (`relevantKeys`) matching the specific RCM test
 *      the user opened, plus `flaggedKeys` for any assertions with mismatches
 *      or unresolved issues. The subset is the backend's `assertion_scope` —
 *      the assertions that decide each item's evaluation — whenever the test
 *      has one; the title heuristic below serves only unscoped tests.
 *
 * Pure and stateless — every number and order comes directly from the payload.
 */

export interface CycleStageGroup {
  id: string
  label: string
  stepIndex: number
  columns: CycleVouchGridColumn[]
  matched: number
  mismatched: number
  review: number
  tone: 'bad' | 'warn' | 'ok' | 'neutral'
}

export interface CycleColumnPlan {
  orderedColumns: CycleVouchGridColumn[]
  stages: CycleStageGroup[]
  columnStageId: Record<string, string>
  relevantKeys: string[]
  flaggedKeys: string[]
}

export interface StageSpan {
  stageId: string
  label: string
  stepIndex: number
  span: number
  tone: CycleStageGroup['tone']
}

interface RoleStageMeta {
  id: string
  label: string
  order: number
}

const FALLBACK_STAGES: Array<{ id: string; label: string; order: number; match: RegExp }> = [
  { id: 'purchase_requisition', label: 'Purchase Requisition', order: 0, match: /^(requisition|req|verification_record|procurement_approval|financial_approval)/i },
  { id: 'purchase_order', label: 'Purchase Order', order: 1, match: /^(order|purchase_order|po\b|po_)/i },
  { id: 'goods_receipt', label: 'Goods Receipt', order: 2, match: /^(receipt|goods_receipt|grn|delivery)/i },
  { id: 'vendor_invoice', label: 'Vendor Invoice', order: 3, match: /^(invoice|vendor_invoice|bill)/i },
  { id: 'payment_voucher', label: 'Payment Voucher', order: 4, match: /^(payment|voucher|bank|disbursement|remittance)/i },
]

const STAGE_TEXT_PATTERNS: Record<string, RegExp[]> = {
  purchase_requisition: [/\brequisitions?\b/i, /\breq\b/i],
  purchase_order: [/\bpurchase orders?\b/i, /\bpos?\b/i, /\borders?\b/i, /\bordered\b/i],
  goods_receipt: [/\bgoods receipts?\b/i, /\bgoods receipt notes?\b/i, /\bgrns?\b/i, /\breceipts?\b/i, /\breceived\b/i, /\binspection\b/i, /\bgoods\b/i],
  vendor_invoice: [/\binvoices?\b/i, /\bverif\w*\b/i],
  payment_voucher: [/\bpayments?\b/i, /\bpaid\b/i, /\bvouchers?\b/i],
}

const FIELD_CONCEPTS: Record<string, RegExp[]> = {
  vendor: [/\bvendor\b/i, /\bsupplier\b/i],
  quantity: [/\bquantit\w*\b/i, /\bqty\b/i],
  amount: [/\bamount\b/i, /\bvalue\b/i, /\bcost\b/i, /\bprice\b/i, /\btotal\b/i],
  description: [/\bdescription\b/i],
  currency: [/\bcurrenc\w*\b/i],
}

const SUBROLE_QUALIFIERS = new Set(['verification', 'verified', 'approval', 'approved', 'inspection', 'inspected'])

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function buildRoleStageMap(payload: CycleVouchGridPayload): Map<string, RoleStageMeta> {
  const map = new Map<string, RoleStageMeta>()
  const docTypeOrder = new Map<string, number>()

  // 1. Prefer the ruleset's authoritative chronological roles when supplied.
  for (const role of payload.roles ?? []) {
    const roleName = String(role.name ?? '').trim()
    const docType = String(role.document_type ?? '').trim() || roleName
    if (!roleName) continue
    if (!docTypeOrder.has(docType)) docTypeOrder.set(docType, docTypeOrder.size)
    map.set(roleName, {
      id: docType,
      label: humanize(docType),
      order: docTypeOrder.get(docType)!,
    })
  }

  // 2. Fall back cleanly for any role not in `payload.roles` (or older payloads).
  let nextCustomOrder = Math.max(10, docTypeOrder.size + 10)
  for (const col of payload.columns) {
    for (const role of col.applicable_roles ?? []) {
      if (!role || map.has(role)) continue
      const hit = FALLBACK_STAGES.find(entry => entry.match.test(role))
      if (hit) {
        map.set(role, { id: hit.id, label: hit.label, order: hit.order })
      } else {
        const key = role.trim()
        map.set(key, { id: key, label: humanize(key), order: nextCustomOrder++ })
      }
    }
  }
  return map
}

function issueCount(col: CycleVouchGridColumn): number {
  const c = col.counts
  return (c.mismatch ?? 0)
    + (c.missing_evidence ?? 0)
    + (c.invalid_extraction ?? 0)
    + (c.ambiguous ?? 0)
    + (c.cannot_determine ?? 0)
}

function columnStages(col: CycleVouchGridColumn, roleMap: Map<string, RoleStageMeta>): RoleStageMeta[] {
  const seen = new Map<string, RoleStageMeta>()
  for (const role of col.applicable_roles ?? []) {
    const meta = roleMap.get(role)
    if (meta && !seen.has(meta.id)) seen.set(meta.id, meta)
  }
  const list = [...seen.values()].sort((a, b) => a.order - b.order)
  return list.length ? list : [{ id: 'general', label: 'Cycle checks', order: 999 }]
}

function stagesInTitle(title: string, allStages: RoleStageMeta[]): Set<string> {
  const found = new Set<string>()
  for (const stage of allStages) {
    const patterns = STAGE_TEXT_PATTERNS[stage.id]
    if (patterns) {
      if (patterns.some(pat => pat.test(title))) found.add(stage.id)
    } else {
      const escaped = stage.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      if (new RegExp(`\\b${escaped}\\b`, 'i').test(title)) found.add(stage.id)
    }
  }
  return found
}

function conceptsInText(text: string): Set<string> {
  const found = new Set<string>()
  for (const [concept, patterns] of Object.entries(FIELD_CONCEPTS)) {
    if (patterns.some(pat => pat.test(text))) found.add(concept)
  }
  return found
}

function pickRelevantKeys(
  payload: CycleVouchGridPayload,
  orderedColumns: CycleVouchGridColumn[],
  roleMap: Map<string, RoleStageMeta>,
): string[] {
  if (Array.isArray(payload.assertion_scope)) {
    const scope = new Set(payload.assertion_scope)
    return orderedColumns.filter(col => scope.has(col.key)).map(col => col.key)
  }
  if (orderedColumns.length <= 1) return orderedColumns.map(c => c.key)
  const title = String(payload.title ?? '').trim()
  if (!title) return []
  const low = title.toLowerCase()

  const allStages = [...new Map([...roleMap.values()].map(m => [m.id, m])).values()]
  const titleStageIds = stagesInTitle(title, allStages)
  const titleConcepts = conceptsInText(title)

  if (!titleStageIds.size && !titleConcepts.size) return []

  const stageOrderById = new Map(allStages.map(s => [s.id, s.order]))
  let downstreamStageId: string | null = null
  let maxOrder = -1
  for (const id of titleStageIds) {
    const order = stageOrderById.get(id) ?? 0
    if (order >= maxOrder) {
      maxOrder = order
      downstreamStageId = id
    }
  }

  const picked: string[] = []
  for (const col of orderedColumns) {
    const roles = col.applicable_roles ?? []
    const stages = columnStages(col, roleMap)
    const stageIds = new Set(stages.map(s => s.id))
    const colText = `${col.key} ${col.label} ${col.requirement ?? ''}`
    const colConcepts = conceptsInText(colText)

    if (titleStageIds.size >= 2) {
      // Every stage touched by this assertion must be part of the test's named scope.
      if (![...stageIds].every(id => titleStageIds.has(id))) continue

      // Must touch the downstream target stage OR explicitly match a sub-role qualifier
      // named in the title (e.g. `invoice_verification` for "changes between verification and payment").
      const subroleHit = roles.some(role =>
        role.toLowerCase().split('_').some(part => SUBROLE_QUALIFIERS.has(part) && low.includes(part)),
      )
      if (downstreamStageId && !stageIds.has(downstreamStageId) && !subroleHit) continue

      // When a title asks about changes "between X and Y", omit single-role completeness checks.
      if (roles.length <= 1 && /\bbetween\b/i.test(low)) continue
    } else if (titleStageIds.size === 1) {
      if (![...stageIds].some(id => titleStageIds.has(id))) continue
    }

    if (titleConcepts.size > 0) {
      if (![...colConcepts].some(c => titleConcepts.has(c))) continue
    }

    picked.push(col.key)
  }

  return picked
}

export function planCycleColumns(payload: CycleVouchGridPayload): CycleColumnPlan {
  const roleMap = buildRoleStageMap(payload)
  const bucketMap = new Map<string, { meta: RoleStageMeta; columns: CycleVouchGridColumn[] }>()
  const columnStageId: Record<string, string> = {}

  for (const col of payload.columns) {
    const stages = columnStages(col, roleMap)
    // Assign each assertion to the downstream (latest) document stage it verifies.
    const target = stages[stages.length - 1]
    columnStageId[col.key] = target.id
    const bucket = bucketMap.get(target.id)
    if (bucket) bucket.columns.push(col)
    else bucketMap.set(target.id, { meta: target, columns: [col] })
  }

  const sortedBuckets = [...bucketMap.values()].sort((a, b) => a.meta.order - b.meta.order)

  const stages: CycleStageGroup[] = sortedBuckets.map((bucket, idx) => {
    // Within each stage, surface mismatched/flagged columns first, preserving original order for ties.
    const cols = [...bucket.columns].sort((a, b) => {
      const aBad = (a.counts.mismatch ?? 0) > 0 ? 2 : issueCount(a) > 0 ? 1 : 0
      const bBad = (b.counts.mismatch ?? 0) > 0 ? 2 : issueCount(b) > 0 ? 1 : 0
      return bBad - aBad
    })
    let matched = 0
    let mismatched = 0
    let review = 0
    for (const c of cols) {
      matched += c.counts.match ?? 0
      mismatched += c.counts.mismatch ?? 0
      review += (c.counts.missing_evidence ?? 0)
        + (c.counts.invalid_extraction ?? 0)
        + (c.counts.ambiguous ?? 0)
        + (c.counts.cannot_determine ?? 0)
    }
    const tone: CycleStageGroup['tone'] = mismatched > 0
      ? 'bad'
      : review > 0
        ? 'warn'
        : matched > 0
          ? 'ok'
          : 'neutral'
    return {
      id: bucket.meta.id,
      label: bucket.meta.label,
      stepIndex: idx + 1,
      columns: cols,
      matched,
      mismatched,
      review,
      tone,
    }
  })

  const orderedColumns = stages.flatMap(stage => stage.columns)
  const flaggedKeys = orderedColumns.filter(col => issueCount(col) > 0).map(col => col.key)
  const relevantKeys = pickRelevantKeys(payload, orderedColumns, roleMap)

  return { orderedColumns, stages, columnStageId, relevantKeys, flaggedKeys }
}

/** Collapse consecutive visible columns sharing a stage into `<th colspan>` spans. */
export function buildStageSpans(
  visibleColumns: CycleVouchGridColumn[],
  plan: CycleColumnPlan,
): StageSpan[] {
  const stageById = new Map(plan.stages.map(s => [s.id, s]))
  const spans: StageSpan[] = []
  for (const col of visibleColumns) {
    const stageId = plan.columnStageId[col.key] ?? 'general'
    const stage = stageById.get(stageId)
    const prev = spans[spans.length - 1]
    if (prev && prev.stageId === stageId) {
      prev.span += 1
    } else {
      spans.push({
        stageId,
        label: stage?.label ?? 'Cycle checks',
        stepIndex: stage?.stepIndex ?? spans.length + 1,
        span: 1,
        tone: stage?.tone ?? 'neutral',
      })
    }
  }
  return spans
}
