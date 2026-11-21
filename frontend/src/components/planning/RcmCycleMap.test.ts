import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { CycleShape, RcmRow } from '../../types'
import RcmCycleMap from './RcmCycleMap.vue'

function makeRow(overrides: Partial<RcmRow> = {}): RcmRow {
  return {
    id: 'RCM-1', semantic_id: 'R1', created_by: 'agent', agent_run_id: null,
    process: 'Raise requisition', risk: 'Risk', risk_rating: 'high', business_cycle: 'Procure-to-pay',
    control_attributes: [], control: 'Control', control_type: '', control_owner: '',
    criteria: '', criteria_refs: [], test_refs: ['datatest:DAT-1'],
    execution_rollup: { tests: 1, completed: 0, exceptions: 0, test_rollups: [] },
    finding_refs: [], evidence_refs: [], prepared_by: null,
    review_status: 'draft', updated: '',
    ...overrides,
  } as unknown as RcmRow
}

const cycle: CycleShape = {
  name: 'Procure-to-pay',
  steps: [
    { name: 'Raise requisition', roles: [], populations: [], themes: [] },
    { name: 'Issue PO', roles: [], populations: [], themes: [] },
    { name: 'Release payment', roles: [], populations: [], themes: [] },
  ],
  cross_cutting: { name: 'Override & segregation', themes: [] },
  created_by: 'agent',
  agent_run_id: null,
  apm_sha1: 'sha',
  updated: null,
}

describe('RcmCycleMap', () => {
  it('orders stages by business cycle and reports risk + Data/Doc test counts', () => {
    const rows = [
      makeRow({ id: 'RCM-1', process: 'Issue PO', test_refs: ['datatest:DAT-1', 'doctest:DT-1'] }),
      makeRow({ id: 'RCM-2', process: 'Raise requisition', risk_rating: 'medium', test_refs: ['datatest:DAT-2'] }),
      makeRow({ id: 'RCM-3', process: 'Override & segregation', test_refs: ['doctest:DT-2'] }),
    ]

    const wrapper = mount(RcmCycleMap, {
      props: { cycle, rows, selectedProcess: null },
    })

    expect(wrapper.text()).toContain('Procure-to-pay lifecycle · 3 stages')
    const names = wrapper.findAll('.stage-name').map(n => n.text())
    expect(names).toEqual(['Raise requisition', 'Issue PO', 'Release payment', 'Override & segregation'])

    const poCard = wrapper.findAll('.stage-card')[1]
    expect(poCard.text()).toContain('1 risk')
    expect(poCard.text()).toContain('1 high')
    expect(poCard.text()).toContain('Data 1')
    expect(poCard.text()).toContain('Doc 1')
  })

  it('toggles stage selection on click and clears via Show all stages', async () => {
    const rows = [
      makeRow({ id: 'RCM-1', process: 'Raise requisition' }),
      makeRow({ id: 'RCM-2', process: 'Issue PO' }),
    ]

    const wrapper = mount(RcmCycleMap, {
      props: { cycle, rows, selectedProcess: null },
    })

    await wrapper.findAll('.stage-card')[1].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['Issue PO'])

    await wrapper.setProps({ selectedProcess: 'Issue PO' })
    await wrapper.find('.clear-btn').trigger('click')
    expect(wrapper.emitted('select')?.[1]).toEqual([null])
  })
})
