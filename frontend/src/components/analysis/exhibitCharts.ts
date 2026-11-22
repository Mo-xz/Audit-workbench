import type { FramePayload, VizSpec } from '../../types'

/**
 * The memo's exhibit forms, laid out as marks.
 *
 * A result frame and its chart spec become a list of primitives — rects,
 * paths, lines, dots and text, each carrying a class for its colour and an
 * optional tooltip — that `ExhibitChart.vue` draws as SVG. Layout lives here,
 * away from the DOM, so every form is testable as numbers; the component only
 * measures its width and renders.
 *
 * The seven forms are the benchmark memo's (docs/sample-procurement/
 * eda-benchmark): horizontal bars with value labels, lines, segmented share
 * bars, a shaded two-way table, a range plot, a log-scale strip and a bridge.
 * A spec the frame cannot satisfy lays out as `null`, and the caller shows the
 * frame as a table instead: a chart drawn from the wrong columns is worse than
 * none.
 */

export type ExhibitForm = 'hbar' | 'bar' | 'line' | 'lines' | 'share' | 'heatmap' | 'range' | 'strip' | 'bridge'
export const EXHIBIT_FORMS: readonly ExhibitForm[] = ['hbar', 'bar', 'line', 'lines', 'share', 'heatmap', 'range', 'strip', 'bridge']

export type Anchor = 'start' | 'middle' | 'end'
export type Mark =
  | { kind: 'rect'; x: number; y: number; w: number; h: number; rx?: number; cls: string; tip?: string[] }
  | { kind: 'path'; d: string; cls: string; tip?: string[] }
  | { kind: 'line'; x1: number; y1: number; x2: number; y2: number; cls: string }
  | { kind: 'polyline'; points: string; cls: string }
  | { kind: 'dot'; cx: number; cy: number; r: number; cls: string; tip?: string[] }
  | { kind: 'text'; x: number; y: number; text: string; cls: string; anchor?: Anchor; rotate?: number }
  | { kind: 'hit'; x: number; y: number; w: number; h: number; tip: string[] }

export interface LegendItem { label: string; cls: string; line?: boolean }
export interface ExhibitLayout { width: number; height: number; marks: Mark[]; legend: LegendItem[]; aria: string }

const CHAR = 6.4 // average glyph width of the 12px label face, for fitting text

/**
 * Roughly how wide `text` sets at 12px. Column names are the common label
 * here, and capitals, digits and underscores set a third wider than lower
 * case: estimated at one average width, `REQUISITION_DATE → VERIFIED_DATE`
 * overran its gutter and was cut at the sheet's edge.
 */
export function textWidth(text: string): number {
  let width = 0
  for (const ch of text) width += /[A-Z0-9_#%@MW]/.test(ch) ? 7.6 : /[ il.,:;'|!]/.test(ch) ? 3.4 : 6.2
  return width
}
const MAX_ROWS = 24

type Cell = string | number | boolean | null

export function isExhibitForm(type: string | undefined): type is ExhibitForm {
  return !!type && (EXHIBIT_FORMS as readonly string[]).includes(type)
}

function column(frame: FramePayload, name: string | undefined): Cell[] | null {
  if (!name) return null
  const index = frame.columns.indexOf(name)
  return index < 0 ? null : frame.rows.map(row => row[index] ?? null)
}

function num(value: Cell): number | null {
  if (value === null || value === '' || typeof value === 'boolean') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

function label(value: Cell): string {
  return value === null || value === '' ? '(blank)' : String(value)
}

/** 645,372,000 → "645.4M"; 12,553,800 → "12.6M"; 85,000 → "85k". */
export function short(value: number, unit = ''): string {
  if (unit === '%') return `${trim(value.toFixed(1))}%`
  const a = Math.abs(value)
  if (a >= 1e9) return `${trim((value / 1e9).toFixed(1))}B`
  if (a >= 1e6) return `${trim((value / 1e6).toFixed(1))}M`
  if (a >= 1e4) return `${Math.round(value / 1e3)}k`
  return Number.isInteger(value) ? value.toLocaleString('en-US') : trim(value.toFixed(2))
}
const trim = (s: string) => s.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
const full = (value: number) => Number.isInteger(value) ? value.toLocaleString('en-US') : value.toLocaleString('en-US', { maximumFractionDigits: 2 })

function fit(text: string, width: number): string {
  if (textWidth(text) <= width) return text
  let out = text
  while (out.length > 3 && textWidth(`${out}…`) > width) out = out.slice(0, -1)
  return `${out}…`
}

/** Round ticks from zero (or a negative floor) to at least `max`. */
export function niceTicks(min: number, max: number, count: number): number[] {
  const span = Math.max(max - min, 1e-9)
  const raw = span / count
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.floor(min / step) * step; v <= max + step * 1e-6; v += step) out.push(+v.toFixed(10))
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step)
  return out
}

/** A bar with a 4px rounded data end and a square baseline. */
function bar(x: number, y: number, w: number, h: number, side: 'right' | 'top'): string {
  const r = Math.max(0, Math.min(4, side === 'right' ? w / 2 : h / 2, side === 'right' ? h / 2 : w / 2))
  if (side === 'right') return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

function rowLabels(names: string[], width: number) {
  const narrow = width < 520
  const labelW = narrow ? 0 : Math.min(Math.max(...names.map(textWidth), 24) + 14, width * 0.4)
  return { narrow, labelW }
}

// --------------------------------------------------------------------- hbar
function hbar(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const names = column(frame, viz.x)
  const series = (viz.y ?? []).map(name => ({ name, values: column(frame, name) })).filter(s => s.values)
  if (!names || !series.length || series.length > 2) return null
  const extras = (viz.label ?? []).map(name => ({ name, values: column(frame, name) })).filter(s => s.values)
  const flags = column(frame, viz.flag)
  const unit = viz.unit ?? ''
  let rows = names.map((name, i) => ({
    name: label(name),
    values: series.map(s => num(s.values![i]) ?? 0),
    extra: extras.map(e => num(e.values![i])).map((v, j) => v === null ? '' : `${short(v, extras[j].name.endsWith('_pct') ? '%' : '')}`).filter(Boolean),
    flag: (num(flags?.[i] ?? null) ?? 0) > 0,
  }))
  if (viz.omit_zero) rows = rows.filter(row => row.values.some(v => v !== 0))
  rows = rows.slice(0, MAX_ROWS)
  if (!rows.length) return null
  const max = Math.max(...rows.flatMap(r => r.values), viz.reference?.value ?? 0, 1e-9)
  const min = Math.min(0, ...rows.flatMap(r => r.values))
  const { narrow, labelW } = rowLabels(rows.map(r => r.name), width)
  const valueText = (row: typeof rows[number], k: number) =>
    [short(row.values[k], unit), ...(k === 0 ? row.extra : [])].join(' · ')
  const right = Math.min(150, Math.max(...rows.map(r => valueText(r, 0).length)) * CHAR + 16)
  const bh = series.length > 1 ? 9 : 14
  const rowH = (narrow ? 22 : 8) + bh * series.length + (series.length - 1) * 2 + (narrow ? 4 : 8)
  const top = viz.reference ? 20 : 4
  const height = top + rows.length * rowH + 22
  const x0 = labelW, x1 = width - right
  const ticks = niceTicks(min, max, narrow ? 3 : 5)
  const lo = ticks[0], hi = ticks[ticks.length - 1]
  const sx = (v: number) => x0 + (x1 - x0) * (v - lo) / (hi - lo)
  const marks: Mark[] = []
  for (const t of ticks) {
    marks.push({ kind: 'line', x1: sx(t), x2: sx(t), y1: top, y2: height - 20, cls: t === 0 ? 'axis' : 'grid' })
    marks.push({ kind: 'text', x: sx(t), y: height - 5, text: short(t, unit), cls: 't-axis', anchor: 'middle' })
  }
  if (viz.reference) {
    const xr = sx(viz.reference.value)
    marks.push({ kind: 'line', x1: xr, x2: xr, y1: top - 4, y2: height - 20, cls: 'reference' })
    marks.push({ kind: 'text', x: xr, y: top - 8, text: viz.reference.label, cls: 't-note', anchor: xr > width - 150 ? 'end' : 'middle' })
  }
  rows.forEach((row, i) => {
    const yRow = top + i * rowH
    const yBars = yRow + (narrow ? 20 : (rowH - (bh * series.length + (series.length - 1) * 2)) / 2)
    marks.push(narrow
      ? { kind: 'text', x: x0, y: yRow + 13, text: fit(row.name, width - 8), cls: 't-label' }
      : { kind: 'text', x: labelW - 10, y: yBars + (bh * series.length) / 2 + 4, text: fit(row.name, labelW - 12), cls: 't-label', anchor: 'end' })
    row.values.forEach((value, k) => {
      const y = yBars + k * (bh + 2)
      const a = sx(Math.min(0, value)), b = sx(Math.max(0, value))
      const cls = row.flag ? 'critical' : k === 0 ? 's1' : 's2'
      if (b - a > 0.5) marks.push({ kind: 'path', d: bar(a, y, Math.max(b - a, 2), bh, 'right'), cls })
      marks.push({ kind: 'text', x: b + 6, y: y + bh / 2 + 4, text: valueText(row, k), cls: 't-value' })
    })
    marks.push({
      kind: 'hit', x: 0, y: yRow, w: width, h: rowH,
      tip: [row.name, ...series.map((s, k) => `${s.name}: ${unit === '%' ? short(row.values[k], unit) : full(row.values[k])}`), ...row.extra],
    })
  })
  return {
    width, height, marks,
    legend: series.length > 1 ? series.map((s, k) => ({ label: s.name, cls: k === 0 ? 's1' : 's2' })) : [],
    aria: `${series.map(s => s.name).join(' and ')} by ${viz.x}`,
  }
}

// --------------------------------------------------------------------- lines
function lines(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const xs = column(frame, viz.x)
  const series = (viz.y ?? []).map(name => ({ name, values: column(frame, name)?.map(num) })).filter(s => s.values)
  if (!xs || !series.length || series.length > 2 || xs.length < 2) return null
  const narrow = width < 560
  const left = 48, right = 16, top = 14, bottom = 28, height = narrow ? 220 : 260
  const all = series.flatMap(s => s.values!.filter((v): v is number => v !== null))
  if (!all.length) return null
  const ticks = niceTicks(Math.min(0, ...all), Math.max(...all), 5)
  const lo = ticks[0], hi = ticks[ticks.length - 1]
  const n = xs.length
  const x = (i: number) => left + (width - left - right) * (i + 0.5) / n
  const y = (v: number) => top + (height - top - bottom) * (1 - (v - lo) / (hi - lo))
  const marks: Mark[] = []
  for (const t of ticks) {
    marks.push({ kind: 'line', x1: left, x2: width - right, y1: y(t), y2: y(t), cls: t === 0 ? 'axis' : 'grid' })
    marks.push({ kind: 'text', x: left - 8, y: y(t) + 4, text: short(t), cls: 't-axis', anchor: 'end' })
  }
  const every = Math.max(1, Math.ceil(n / Math.floor((width - left - right) / 46)))
  xs.forEach((value, i) => {
    if (i % every) return
    const text = String(value ?? '').replace(/^(\d{4})-(\d{2})-01$/, (_m, yy, mm) =>
      new Date(`${yy}-${mm}-01T00:00:00`).toLocaleString('en-GB', { month: 'short' }) + (mm === '01' || i === 0 ? ` ${yy.slice(2)}` : ''))
    marks.push({ kind: 'text', x: x(i), y: height - 10, text, cls: 't-axis', anchor: 'middle' })
  })
  series.forEach((s, k) => {
    const cls = k === 0 ? 's1' : 's2'
    const points = s.values!.map((v, i) => v === null ? null : `${x(i)},${y(v)}`).filter(Boolean).join(' ')
    marks.push({ kind: 'polyline', points, cls: `line ${cls}` })
    s.values!.forEach((v, i) => { if (v !== null) marks.push({ kind: 'dot', cx: x(i), cy: y(v), r: 3.5, cls: `${cls} ring` }) })
  })
  const slot = (width - left - right) / n
  xs.forEach((value, i) => marks.push({
    kind: 'hit', x: x(i) - slot / 2, y: top, w: slot, h: height - top - bottom,
    tip: [String(value ?? ''), ...series.map(s => `${s.name}: ${s.values![i] === null ? '—' : full(s.values![i]!)}`)],
  }))
  return {
    width, height, marks,
    legend: series.length > 1 ? series.map((s, k) => ({ label: s.name, cls: k === 0 ? 's1' : 's2', line: true })) : [],
    aria: `${series.map(s => s.name).join(' and ')} by ${viz.x}`,
  }
}

// --------------------------------------------------------------------- share
function share(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const parts = column(frame, viz.x)
  const series = (viz.y ?? []).map(name => ({ name, values: column(frame, name)?.map(v => num(v) ?? 0) })).filter(s => s.values)
  if (!parts || !series.length || parts.length > 5) return null
  const marks: Mark[] = []
  const bh = 28, gap = 2, block = 62
  series.forEach((s, i) => {
    const total = s.values!.reduce((a, b) => a + b, 0)
    if (!total) return
    const y0 = i * block
    marks.push({ kind: 'text', x: 0, y: y0 + 14, text: s.name.replace(/_pct$/, '').replace(/_/g, ' '), cls: 't-label' })
    const avail = width - gap * (parts.length - 1)
    let x = 0
    s.values!.forEach((value, j) => {
      const w = avail * value / total
      if (w <= 0) return
      const name = label(parts[j])
      const share = `${trim((100 * value / total).toFixed(1))}%`
      marks.push({ kind: 'rect', x, y: y0 + 22, w, h: bh, rx: 4, cls: `ord-${j + 1}`, tip: [name, `${s.name}: ${share}`] })
      if (share.length * CHAR + 14 < w) marks.push({ kind: 'text', x: x + 7, y: y0 + 22 + bh / 2 + 4, text: share, cls: `t-in ord-ink-${j + 1}` })
      x += w + gap
    })
  })
  return {
    width, height: series.length * block + 6, marks,
    legend: parts.map((p, j) => ({ label: label(p), cls: `ord-${j + 1}` })),
    aria: `Shares of ${series.map(s => s.name).join(' and ')} by ${viz.x}`,
  }
}

// ------------------------------------------------------------------- heatmap
interface Grid { rows: string[]; cols: string[]; value: (r: number, c: number) => number | null; flag: (r: number, c: number) => boolean }

function grid(frame: FramePayload, viz: VizSpec): Grid | null {
  if (viz.row) {
    const rows = column(frame, viz.row), cols = column(frame, viz.x), values = column(frame, viz.y?.[0])
    if (!rows || !cols || !values) return null
    const flags = column(frame, viz.flag)
    const r = [...new Set(rows.map(label))], c = [...new Set(cols.map(label))]
    const at = new Map<string, number>()
    rows.forEach((row, i) => at.set(`${label(row)}\u0000${label(cols[i])}`, i))
    const find = (i: number, j: number) => at.get(`${r[i]}\u0000${c[j]}`)
    return {
      rows: r, cols: c,
      value: (i, j) => { const k = find(i, j); return k === undefined ? null : num(values[k]) },
      flag: (i, j) => { const k = find(i, j); return k !== undefined && (num(flags?.[k] ?? null) ?? 0) > 0 },
    }
  }
  const names = column(frame, viz.x)
  if (!names) return null
  const skip = new Set([viz.x, ...(viz.exclude ?? [])])
  const cols = frame.columns.filter((name, i) => !skip.has(name) && /Int|Float|UInt|Decimal/.test(frame.dtypes[i] ?? ''))
  if (!cols.length) return null
  const index = cols.map(name => frame.columns.indexOf(name))
  return {
    rows: names.map(label), cols,
    value: (i, j) => num(frame.rows[i][index[j]] ?? null),
    flag: () => false,
  }
}

function heatmap(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const g = grid(frame, viz)
  if (!g || !g.rows.length || g.rows.length > MAX_ROWS || g.cols.length > 16) return null
  const unit = viz.unit ?? ''
  const values = g.rows.flatMap((_, i) => g.cols.map((__, j) => g.value(i, j) ?? 0))
  const max = Math.max(...values, 1e-9)
  const labelW = Math.min(Math.max(...g.rows.map(textWidth), 24) + 14, width * 0.32)
  const cellW = Math.min(64, (width - labelW) / g.cols.length)
  const rotate = Math.max(...g.cols.map(textWidth)) > cellW - 4
  const head = rotate ? Math.min(110, Math.max(...g.cols.map(textWidth)) * 0.72 + 14) : 24
  const cellH = 26
  const marks: Mark[] = []
  g.cols.forEach((name, j) => {
    const cx = labelW + j * cellW + cellW / 2
    marks.push(rotate
      ? { kind: 'text', x: cx + 4, y: head - 6, text: fit(name, 150), cls: 't-head', anchor: 'start', rotate: -40 }
      : { kind: 'text', x: cx, y: head - 8, text: name, cls: 't-head', anchor: 'middle' })
  })
  g.rows.forEach((name, i) => {
    const y = head + i * cellH
    marks.push({ kind: 'text', x: labelW - 10, y: y + cellH / 2 + 4, text: fit(name, labelW - 12), cls: 't-label', anchor: 'end' })
    g.cols.forEach((col, j) => {
      const x = labelW + j * cellW
      const value = g.value(i, j)
      if (!value) {
        marks.push({ kind: 'text', x: x + cellW / 2, y: y + cellH / 2 + 4, text: '·', cls: 't-empty', anchor: 'middle' })
        return
      }
      const step = Math.max(1, Math.ceil(6 * value / max))
      const breach = g.flag(i, j)
      marks.push({ kind: 'rect', x: x + 1, y: y + 1, w: cellW - 2, h: cellH - 2, rx: 3, cls: `seq-${step}${breach ? ' breach' : ''}`, tip: [`${name} · ${col}`, short(value, unit) + (breach ? ' — above the limit' : '')] })
      const text = short(value, unit)
      if (text.length * CHAR < cellW - 4) marks.push({ kind: 'text', x: x + cellW / 2, y: y + cellH / 2 + 4, text, cls: `t-cell seq-ink-${step}`, anchor: 'middle' })
    })
  })
  return {
    width: Math.min(width, labelW + cellW * g.cols.length + (rotate ? 60 : 0)),
    height: head + g.rows.length * cellH + 4, marks, legend: [],
    aria: viz.row ? `${viz.y?.[0]} by ${viz.row} and ${viz.x}` : `${viz.x} against ${g.cols.length} columns`,
  }
}

// --------------------------------------------------------------------- range
function range(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const names = column(frame, viz.x)
  const [lo, q1, med, q3, hi] = (viz.y ?? []).map(name => column(frame, name)?.map(num))
  if (!names || !lo || !q1 || !med || !q3 || !hi) return null
  const flags = column(frame, viz.flag)
  const rows = names.map((name, i) => ({
    name: label(name), min: lo[i], p25: q1[i], med: med[i], p75: q3[i], max: hi[i], flagged: num(flags?.[i] ?? null) ?? 0,
  })).filter(r => r.min !== null && r.max !== null).slice(0, MAX_ROWS)
  if (!rows.length) return null
  const { narrow, labelW } = rowLabels(rows.map(r => r.name), width)
  const rowH = narrow ? 44 : 30, top = 6, right = 20
  const height = top + rows.length * rowH + 26
  const ticks = niceTicks(Math.min(0, ...rows.map(r => r.min!)), Math.max(...rows.map(r => r.max!)), narrow ? 4 : 6)
  const a = ticks[0], b = ticks[ticks.length - 1]
  const x0 = labelW, x1 = width - right
  const sx = (v: number) => x0 + (x1 - x0) * (v - a) / (b - a)
  const marks: Mark[] = []
  ticks.forEach((t, i) => {
    marks.push({ kind: 'line', x1: sx(t), x2: sx(t), y1: top, y2: height - 22, cls: t === 0 ? 'reference' : 'grid' })
    marks.push({ kind: 'text', x: sx(t), y: height - 6, text: `${short(t)}${i === ticks.length - 1 ? ' days' : ''}`, cls: 't-axis', anchor: 'middle' })
  })
  rows.forEach((r, i) => {
    const yRow = top + i * rowH, yc = yRow + (narrow ? 30 : rowH / 2)
    marks.push(narrow
      ? { kind: 'text', x: x0, y: yRow + 13, text: fit(r.name, width - 8), cls: 't-label' }
      : { kind: 'text', x: labelW - 10, y: yc + 4, text: fit(r.name, labelW - 12), cls: 't-label', anchor: 'end' })
    if (r.min! < 0) {
      marks.push({ kind: 'line', x1: sx(r.min!), x2: sx(0), y1: yc, y2: yc, cls: 'whisker critical' })
      marks.push({ kind: 'dot', cx: sx(r.min!), cy: yc, r: 4, cls: 'critical ring' })
      if (r.flagged) marks.push({ kind: 'text', x: (sx(r.min!) + sx(0)) / 2, y: yc - 7, text: `${r.flagged} before the prior step`, cls: 't-crit', anchor: 'middle' })
    }
    marks.push({ kind: 'line', x1: sx(Math.max(r.min!, 0)), x2: sx(r.max!), y1: yc, y2: yc, cls: 'whisker quiet' })
    if (r.p25 !== null && r.p75 !== null) {
      const left = sx(Math.max(r.p25, r.min!))
      marks.push({ kind: 'rect', x: left, y: yc - 5, w: Math.max(sx(r.p75) - left, 3), h: 10, rx: 3, cls: 'box' })
    }
    if (r.med !== null) marks.push({ kind: 'dot', cx: sx(r.med), cy: yc, r: 4.5, cls: 's1 ring' })
    marks.push({
      kind: 'hit', x: 0, y: yRow, w: width, h: rowH,
      tip: [r.name, `Median ${r.med ?? '—'} · middle half ${r.p25 ?? '—'} to ${r.p75 ?? '—'}`, `Range ${r.min} to ${r.max}`,
        ...(r.flagged ? [`${r.flagged} ran before the previous step`] : [])],
    })
  })
  return { width, height, marks, legend: [], aria: `Spread of ${viz.x}` }
}

// --------------------------------------------------------------------- strip
function strip(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const names = column(frame, viz.x)
  const series = (viz.y ?? []).map(name => column(frame, name)?.map(num))
  if (!names || series.length < 2 || series.some(s => !s)) return null
  const mid = series[Math.floor(series.length / 2)]!
  const rows = names.map((name, i) => ({
    name: label(name),
    values: [...new Set(series.map(s => s![i]).filter((v): v is number => v !== null && v > 0))],
    centre: mid[i],
  })).filter(r => r.values.length).slice(0, MAX_ROWS)
  if (!rows.length) return null
  const all = rows.flatMap(r => r.values)
  const log = viz.log !== false
  const lo = log ? Math.floor(Math.log10(Math.min(...all))) : 0
  const hi = log ? Math.ceil(Math.log10(Math.max(...all)) + 1e-9) : Math.max(...all)
  const { narrow, labelW } = rowLabels(rows.map(r => r.name), width)
  const rowH = narrow ? 40 : 28, top = 6, right = 64
  const height = top + rows.length * rowH + 26
  const x0 = labelW + 8, x1 = width - right
  const sx = (v: number) => log
    ? x0 + (x1 - x0) * (Math.log10(v) - lo) / Math.max(hi - lo, 1)
    : x0 + (x1 - x0) * v / (hi || 1)
  const marks: Mark[] = []
  const ticks = log ? Array.from({ length: hi - lo + 1 }, (_, k) => Math.pow(10, lo + k)) : niceTicks(0, hi, 5)
  for (const t of ticks) {
    marks.push({ kind: 'line', x1: sx(t), x2: sx(t), y1: top, y2: height - 22, cls: 'grid' })
    marks.push({ kind: 'text', x: sx(t), y: height - 6, text: short(t), cls: 't-axis', anchor: 'middle' })
  }
  rows.forEach((r, i) => {
    const yRow = top + i * rowH, yc = yRow + (narrow ? 28 : rowH / 2)
    marks.push(narrow
      ? { kind: 'text', x: 0, y: yRow + 12, text: fit(r.name, width - 8), cls: 't-label' }
      : { kind: 'text', x: labelW - 4, y: yc + 4, text: fit(r.name, labelW - 8), cls: 't-label', anchor: 'end' })
    marks.push({ kind: 'line', x1: x0, x2: x1, y1: yc, y2: yc, cls: 'grid' })
    const centre = r.centre ?? Math.min(...r.values)
    r.values.forEach(v => {
      const ratio = centre ? v / centre : 1
      const out = ratio >= 3 || ratio <= 1 / 3
      marks.push({ kind: 'dot', cx: sx(v), cy: yc, r: 5, cls: `${out ? 'critical' : 's1'} ring`, tip: [r.name, full(v), ...(out ? [`${trim(ratio.toFixed(1))}× the group's median`] : [])] })
      if (out) marks.push({ kind: 'text', x: sx(v) + 10, y: yc + 4, text: `${trim(ratio.toFixed(1))}×`, cls: 't-crit' })
    })
    if (r.values.length === 1) marks.push({ kind: 'text', x: sx(r.values[0]) + 10, y: yc + 4, text: 'one value', cls: 't-axis' })
  })
  return { width, height, marks, legend: [], aria: `${viz.y?.join(', ')} by ${viz.x}${log ? ', log scale' : ''}` }
}

// -------------------------------------------------------------------- bridge
function bridge(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  const names = column(frame, viz.x), totals = column(frame, viz.y?.[0])?.map(num)
  if (!names || !totals || names.length < 2 || totals.some(v => v === null)) return null
  type Step = { name: string; from: number; to: number; kind: 'total' | 'up' | 'down' }
  const steps: Step[] = []
  names.forEach((name, i) => {
    const value = totals[i]!
    if (i > 0) {
      const prev = totals[i - 1]!
      if (Math.abs(value - prev) > 1e-6) steps.push({ name: value > prev ? 'Added' : 'Fell away', from: prev, to: value, kind: value > prev ? 'up' : 'down' })
    }
    steps.push({ name: label(name), from: 0, to: value, kind: 'total' })
  })
  const { narrow, labelW } = rowLabels(steps.map(s => s.name), width)
  const rowH = narrow ? 46 : 34, bh = 20, top = 6, right = 96
  const height = top + steps.length * rowH + 26
  const max = Math.max(...totals.map(v => v!))
  const ticks = niceTicks(0, max, narrow ? 3 : 5)
  const x0 = labelW, x1 = width - right
  const sx = (v: number) => x0 + (x1 - x0) * v / ticks[ticks.length - 1]
  const marks: Mark[] = []
  for (const t of ticks) {
    marks.push({ kind: 'line', x1: sx(t), x2: sx(t), y1: top, y2: height - 22, cls: t === 0 ? 'axis' : 'grid' })
    marks.push({ kind: 'text', x: sx(t), y: height - 6, text: short(t), cls: 't-axis', anchor: 'middle' })
  }
  steps.forEach((s, i) => {
    const yRow = top + i * rowH, y = yRow + (narrow ? 18 : (rowH - bh) / 2)
    marks.push(narrow
      ? { kind: 'text', x: x0, y: yRow + 12, text: fit(s.name, width - 8), cls: s.kind === 'total' ? 't-label' : 't-note' }
      : { kind: 'text', x: labelW - 10, y: y + bh / 2 + 4, text: fit(s.name, labelW - 12), cls: s.kind === 'total' ? 't-label' : 't-note', anchor: 'end' })
    const a = sx(Math.min(s.from, s.to)), b = sx(Math.max(s.from, s.to))
    const delta = s.to - s.from
    if (s.kind === 'total') marks.push({ kind: 'path', d: bar(a, y, Math.max(b - a, 2), bh, 'right'), cls: 's1' })
    else marks.push({ kind: 'rect', x: a, y, w: Math.max(b - a, 3), h: bh, rx: 2, cls: s.kind === 'up' ? 'critical' : 'quiet' })
    marks.push({ kind: 'text', x: b + 8, y: y + bh / 2 + 4, text: s.kind === 'total' ? short(s.to) : `${delta > 0 ? '+' : '−'}${short(Math.abs(delta))}`, cls: s.kind === 'up' ? 't-crit' : 't-strong' })
    if (i < steps.length - 1) {
      const nx = s.kind === 'down' ? sx(s.to) : b
      marks.push({ kind: 'line', x1: nx, x2: nx, y1: y + bh, y2: y + rowH, cls: 'axis' })
    }
    marks.push({ kind: 'hit', x: 0, y: yRow, w: width, h: rowH, tip: [s.name, s.kind === 'total' ? full(s.to) : `${delta > 0 ? '+' : '−'}${full(Math.abs(delta))}`] })
  })
  return { width, height, marks, legend: [], aria: `Value carried from ${label(names[0])} to ${label(names[names.length - 1])}` }
}

/** Lay out one exhibit, or `null` when the frame cannot carry its form. */
export function layoutExhibit(frame: FramePayload, viz: VizSpec, width: number): ExhibitLayout | null {
  if (!frame.rows.length || width < 120) return null
  switch (viz.type) {
    case 'hbar': case 'bar': return hbar(frame, viz, width)
    case 'line': case 'lines': return lines(frame, viz, width)
    case 'share': return share(frame, viz, width)
    case 'heatmap': return heatmap(frame, viz, width)
    case 'range': return range(frame, viz, width)
    case 'strip': return strip(frame, viz, width)
    case 'bridge': return bridge(frame, viz, width)
    default: return null
  }
}
