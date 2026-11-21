import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DocTestStoryStrip from './DocTestStoryStrip.vue'

describe('DocTestStoryStrip', () => {
  it('renders 3-step AI evidence vouching story with stacked verification bar', () => {
    const wrapper = mount(DocTestStoryStrip, {
      props: {
        aiAuthored: true,
        engineLabel: '3-way cycle vouch',
        ruleTitle: '6 cross-document assertions',
        scopeLabel: 'Requisition → Purchase Order → Goods Receipt → Invoice',
        ran: true,
        passedCount: 10,
        failedCount: 1,
        reviewCount: 1,
        totalCount: 12,
        unitLabel: 'checks',
        evidenceBadge: 'Page-cited extractions',
        coverageMeta: '2 transactions vouched · 1 failed',
        humanTitle: '2 of 2 transactions awaiting call',
        humanDetail: 'Confirm or flag each transaction below.',
        humanTone: 'warn',
        humanBadge: 'Human review',
      },
    })

    const text = wrapper.text()
    expect(text).toContain('AI authored')
    expect(text).toContain('3-way cycle vouch')
    expect(text).toContain('Page-cited extractions')
    expect(text).toContain('1 of 12 checks flagged')
    expect(text).toContain('2 of 2 transactions awaiting call')
    expect(wrapper.find('.seg-ok').exists()).toBe(true)
    expect(wrapper.find('.seg-warn').exists()).toBe(true)
    expect(wrapper.find('.seg-bad').exists()).toBe(true)
  })

  it('renders clean verified state and auditor sign-off', () => {
    const wrapper = mount(DocTestStoryStrip, {
      props: {
        aiAuthored: false,
        engineLabel: 'Document Q&A',
        ruleTitle: 'Purchase Requisition · 5 fields checked',
        ran: true,
        passedCount: 4,
        failedCount: 0,
        reviewCount: 0,
        totalCount: 4,
        unitLabel: 'records',
        humanTitle: 'Signed off · Effective',
        humanDetail: 'All records reviewed.',
        humanTone: 'ok',
        humanBadge: 'Auditor signed off',
      },
    })

    expect(wrapper.text()).toContain('Auditor authored')
    expect(wrapper.text()).toContain('4 of 4 records verified')
    expect(wrapper.text()).toContain('Signed off · Effective')
    expect(wrapper.find('.seg-bad').exists()).toBe(false)
    expect(wrapper.find('.seg-ok').attributes('style')).toContain('width: 100%')
  })
})
