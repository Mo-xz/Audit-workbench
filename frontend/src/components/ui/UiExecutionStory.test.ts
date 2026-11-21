import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import UiExecutionStory from './UiExecutionStory.vue'

describe('UiExecutionStory', () => {
  it('renders the AI authored -> Local Polars -> Human in the loop story with population bar', () => {
    const wrapper = mount(UiExecutionStory, {
      props: {
        aiAuthored: true,
        engineLabel: 'Polars steps',
        ruleTitle: '3 Polars checks',
        scopeLabel: 'invoice_data → po_data',
        ran: true,
        population: 200,
        exceptions: 6,
        tracksExceptions: true,
        humanTitle: '6 open exceptions to rule on',
        humanDetail: 'Review exception groups below.',
        humanTone: 'warn',
        humanBadge: 'Human in the loop',
      },
    })

    const text = wrapper.text()
    expect(text).toContain('AI authored')
    expect(text).toContain('Polars steps')
    expect(text).toContain('invoice_data → po_data')
    expect(text).toContain('Local Polars')
    expect(text).toContain('0 rows sent to AI')
    expect(text).toContain('6 of 200 flagged')
    expect(text).toContain('3%')
    expect(text).toContain('100% of 200 rows scanned')
    expect(text).toContain('6 open exceptions to rule on')
    expect(wrapper.find('.bar-ok').attributes('style')).toContain('width: 97%')
    expect(wrapper.find('.bar-exc').attributes('style')).toContain('width: 3%')
  })

  it('renders auditor-authored clean state and signed-off status', () => {
    const wrapper = mount(UiExecutionStory, {
      props: {
        aiAuthored: false,
        engineLabel: 'Library test',
        ruleTitle: 'Duplicate invoices',
        scopeLabel: 'invoice_data',
        ran: true,
        population: 120,
        exceptions: 0,
        tracksExceptions: true,
        humanTitle: 'Signed off · Effective',
        humanDetail: 'Auditor reviewed the evidence.',
        humanTone: 'ok',
        humanBadge: 'Auditor signed off',
      },
    })

    const text = wrapper.text()
    expect(text).toContain('Auditor authored')
    expect(text).toContain('0 exceptions in 120 rows')
    expect(text).toContain('Auditor signed off')
    expect(wrapper.find('.bar-exc').exists()).toBe(false)
    expect(wrapper.find('.bar-ok').attributes('style')).toContain('width: 100%')
  })

  it('shows ready-to-run state before execution and surfaces execution errors', () => {
    const notRun = mount(UiExecutionStory, {
      props: {
        aiAuthored: true,
        engineLabel: 'Polars Python',
        ruleTitle: 'Custom exception rule',
        ran: false,
        humanTitle: 'Awaiting local run',
        humanDetail: 'Click Run above.',
        humanTone: 'neutral',
      },
    })
    expect(notRun.text()).toContain('Ready to run locally')
    expect(notRun.find('.pop-bar').exists()).toBe(false)

    const errored = mount(UiExecutionStory, {
      props: {
        aiAuthored: true,
        engineLabel: 'Polars Python',
        ruleTitle: 'Custom exception rule',
        ran: true,
        executionError: 'Column vendor_id not found',
        humanTitle: 'Needs auditor review',
        humanDetail: 'Inspect script.',
        humanTone: 'bad',
      },
    })
    expect(errored.text()).toContain('Execution failed')
    expect(errored.text()).toContain('Column vendor_id not found')
  })
})
