import { describe, expect, it } from 'vitest'

import type { FramePayload, VizSpec } from '../../types'
import { layoutExhibit, niceTicks, short } from './exhibitCharts'
import type { Mark } from './exhibitCharts'

// Frames shaped as the profile returns them on the procurement pack.
const frame = (columns: string[], dtypes: string[], rows: FramePayload['rows']): FramePayload => ({ columns, dtypes, rows })
const texts = (marks: Mark[]) => marks.flatMap(m => (m.kind === 'text' ? [m.text] : []))
const classes = (marks: Mark[]) => marks.flatMap(m => ('cls' in m ? [m.cls] : []))
const lay = (f: FramePayload, viz: VizSpec, width = 720) => {
  const layout = layoutExhibit(f, viz, width)
  if (!layout) throw new Error('no layout')
  return layout
}

describe('exhibit layouts', () => {
  it('formats figures the way the memo states them', () => {
    expect(short(645_372_000)).toBe('645.4M')
    expect(short(12_553_800)).toBe('12.6M')
    expect(short(85_000)).toBe('85k')
    expect(short(27.3, '%')).toBe('27.3%')
    expect(niceTicks(0, 291_790_000, 5)).toEqual([0, 100_000_000, 200_000_000, 300_000_000])
  })

  it('draws bars with their value and share, and a breach in red', () => {
    const f = frame(['dept', 'rows', 'value', 'share_pct'], ['String', 'UInt32', 'Float64', 'Float64'], [
      ['Facilities', 9, 291_790_000, 45.2],
      ['Human Resources', 10, 110_620_000, 17.1],
    ])
    const layout = lay(f, { type: 'hbar', x: 'dept', y: ['value'], label: ['share_pct'] })
    expect(texts(layout.marks)).toContain('291.8M · 45.2%')
    expect(texts(layout.marks)).toContain('Facilities')
    expect(layout.legend).toEqual([])
    const flagged = lay(frame(['step', 'n', 'over'], ['String', 'Int64', 'Int64'], [['A', 3, 1], ['B', 2, 0]]),
      { type: 'hbar', x: 'step', y: ['n'], flag: 'over' })
    expect(classes(flagged.marks).filter(c => c === 'critical')).toHaveLength(1)
  })

  it('leaves out zero rows when asked and marks the chance line', () => {
    const f = frame(['column', 'blank'], ['String', 'Int64'], [['A', 0], ['B', 3], ['C', 0]])
    expect(texts(lay(f, { type: 'hbar', x: 'column', y: ['blank'], omit_zero: true }).marks)).not.toContain('A')
    const weekend = frame(['column', 'weekend_pct'], ['String', 'Float64'], [['PO_DATE', 27.3]])
    const layout = lay(weekend, { type: 'hbar', x: 'column', y: ['weekend_pct'], unit: '%', reference: { value: 28.6, label: '28.6%: dates at random' } })
    expect(texts(layout.marks)).toContain('28.6%: dates at random')
    expect(classes(layout.marks)).toContain('reference')
  })

  it('splits two measures into segmented share bars with a legend', () => {
    const f = frame(['band', 'rows_pct', 'value_pct'], ['String', 'Float64', 'Float64'], [
      ['Up to 1M', 60, 5], ['1M to 10M', 30, 25], ['Over 10M', 10, 70],
    ])
    const layout = lay(f, { type: 'share', x: 'band', y: ['rows_pct', 'value_pct'] })
    expect(layout.legend.map(item => item.label)).toEqual(['Up to 1M', '1M to 10M', 'Over 10M'])
    expect(texts(layout.marks)).toEqual(expect.arrayContaining(['rows', 'value', '70%']))
  })

  it('shades a wide two-way table without its total, and pivots a long one', () => {
    const wide = frame(['dept', 'ATM', 'UPS', 'total'], ['String', 'UInt32', 'UInt32', 'UInt32'], [['HR', 1, 3, 4], ['IT', 0, 2, 2]])
    const layout = lay(wide, { type: 'heatmap', x: 'dept', exclude: ['total'] })
    expect(texts(layout.marks)).not.toContain('total')
    expect(classes(layout.marks).some(c => c.startsWith('seq-6'))).toBe(true)
    const long = frame(['band', 'JOB_TITLE', 'approvals', 'over_limit'], ['String', 'String', 'UInt32', 'UInt32'], [
      ['Up to 1M', 'Head of Treasury', 13, 0], ['Over 10M', 'Financial Controller', 2, 2],
    ])
    const grid = lay(long, { type: 'heatmap', row: 'band', x: 'JOB_TITLE', y: ['approvals'], flag: 'over_limit' })
    expect(classes(grid.marks).filter(c => c.includes('breach'))).toHaveLength(1)
    expect(texts(grid.marks)).toEqual(expect.arrayContaining(['Up to 1M', 'Over 10M', '13']))
  })

  it('draws a step that ran before the one it follows in red', () => {
    const f = frame(['step', 'min', 'p25', 'median', 'p75', 'max', 'before_previous'],
      ['String', 'Int64', 'Float64', 'Float64', 'Float64', 'Int64', 'Int64'], [
        ['PO → GRN', -12, 3, 6, 9, 21, 4], ['GRN → invoice', 1, 2, 3, 4, 8, 0],
      ])
    const layout = lay(f, { type: 'range', x: 'step', y: ['min', 'p25', 'median', 'p75', 'max'], flag: 'before_previous' })
    expect(texts(layout.marks)).toContain('4 before the prior step')
    expect(classes(layout.marks)).toContain('whisker critical')
  })

  it('names the one price that breaks its group on a log scale', () => {
    const f = frame(['item', 'min_ratio', 'median_ratio', 'max_ratio'], ['String', 'Float64', 'Float64', 'Float64'], [
      ['ATM cash cassettes', 95_000, 95_000, 95_000], ['Onboarding kits', 80_000, 80_000, 3_000_000],
    ])
    const layout = lay(f, { type: 'strip', x: 'item', y: ['min_ratio', 'median_ratio', 'max_ratio'], log: true })
    expect(texts(layout.marks)).toContain('37.5×')
    expect(texts(layout.marks)).toContain('one value')
  })

  it('bridges each step to the next by what fell away and what was added', () => {
    const f = frame(['column', 'total'], ['String', 'Float64'], [
      ['ESTIMATED_TOTAL_COST', 645_372_000], ['PO_TOTAL_AMOUNT', 609_982_000], ['INVOICE_AMOUNT', 622_535_800],
    ])
    const layout = lay(f, { type: 'bridge', x: 'column', y: ['total'] })
    expect(texts(layout.marks)).toEqual(expect.arrayContaining(['645.4M', '−35.4M', '610M', '+12.6M', '622.5M']))
    expect(texts(layout.marks)).toEqual(expect.arrayContaining(['Fell away', 'Added']))
  })

  it('carries two series as lines with a legend', () => {
    const f = frame(['period', 'committed', 'paid'], ['Date', 'Float64', 'Float64'], [
      ['2024-01-01', 10, 2], ['2024-02-01', 20, 8], ['2024-03-01', 5, 30],
    ])
    const layout = lay(f, { type: 'lines', x: 'period', y: ['committed', 'paid'] })
    expect(layout.legend.map(item => item.label)).toEqual(['committed', 'paid'])
    expect(layout.marks.filter(m => m.kind === 'polyline')).toHaveLength(2)
    expect(texts(layout.marks)).toContain('Jan 24')
  })

  it('declines a spec its frame cannot carry, so the table is shown instead', () => {
    const f = frame(['a', 'b'], ['String', 'Int64'], [['x', 1]])
    expect(layoutExhibit(f, { type: 'hbar', x: 'missing', y: ['b'] }, 600)).toBeNull()
    expect(layoutExhibit(f, { type: 'bridge', x: 'a', y: ['b'] }, 600)).toBeNull()
    expect(layoutExhibit(f, { type: 'table' }, 600)).toBeNull()
  })
})
