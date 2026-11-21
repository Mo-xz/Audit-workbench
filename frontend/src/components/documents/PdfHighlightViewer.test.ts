import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import PdfHighlightViewer from './PdfHighlightViewer.vue'
import type { DocumentHighlightItem, DocumentNoteMarker } from '../../types'

const ITEMS: DocumentHighlightItem[] = [
  {
    key: '0:vendor_name:0',
    field_name: 'vendor_name',
    value: 'OfficeSupply Co.',
    citation_id: 'c2',
    page: 1,
    boxes: [{ x: 0.34, y: 0.15, width: 0.12, height: 0.02 }],
  },
  {
    key: '0:invoice_amount:0',
    field_name: 'invoice_amount',
    value: 'PKR 2,000,000.00',
    citation_id: 'c12',
    page: 1,
    boxes: [{ x: 0.34, y: 0.47, width: 0.14, height: 0.02 }],
  },
]

const NOTES: DocumentNoteMarker[] = [
  {
    key: 'note:1',
    number: 1,
    text: 'No tax registration number or tax amount printed on this TAX INVOICE.',
    page: 1,
    x: 0.42,
    y: 0.08,
    anchored: true,
    box: { x: 0.07, y: 0.06, width: 0.3, height: 0.03 },
  },
  {
    key: 'note:2',
    number: 2,
    text: 'No signature or approval block appears anywhere on the page.',
    page: 1,
    x: 0.92,
    y: 0.89,
    anchored: false,
    box: null,
  },
]

describe('PdfHighlightViewer', () => {
  it('renders highlight boxes after the page image loads and emits hover/select events', async () => {
    const wrapper = mount(PdfHighlightViewer, {
      props: {
        workspaceId: 'procurement',
        documentId: '61419adb82',
        page: 1,
        pageCount: 1,
        items: ITEMS,
        notes: NOTES,
      },
    })

    await wrapper.find('img.pdf-page-img').trigger('load')
    const boxes = wrapper.findAll('button.hl-box')
    expect(boxes).toHaveLength(2)
    expect(boxes[0].text()).toContain('Vendor name')

    await boxes[0].trigger('mouseenter')
    expect(wrapper.emitted('hover')?.[0]).toEqual(['0:vendor_name:0'])

    await boxes[1].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual([ITEMS[1]])

    // Numbered audit note pins render and emit select-note on click
    const pins = wrapper.findAll('button.note-pin')
    expect(pins).toHaveLength(2)
    expect(pins[0].text()).toBe('1')
    await pins[0].trigger('click')
    expect(wrapper.emitted('select-note')?.[0]).toEqual([NOTES[0]])
  })

  it('shows the full audit note callout when activeNoteKey matches a pin and steps to next', async () => {
    const wrapper = mount(PdfHighlightViewer, {
      props: {
        workspaceId: 'procurement',
        documentId: '61419adb82',
        page: 1,
        pageCount: 1,
        items: ITEMS,
        notes: NOTES,
        activeNoteKey: 'note:1',
      },
    })

    await wrapper.find('img.pdf-page-img').trigger('load')
    const callout = wrapper.find('.note-callout')
    expect(callout.exists()).toBe(true)
    expect(callout.text()).toContain('Audit note #1')
    expect(callout.text()).toContain('No tax registration number')

    await callout.find('button[aria-label="Next note"]').trigger('click')
    expect(wrapper.emitted('select-note')?.[0]).toEqual([NOTES[1]])
  })
})
