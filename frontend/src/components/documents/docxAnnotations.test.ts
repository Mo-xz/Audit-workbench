import { describe, expect, it, vi } from 'vitest'

import { annotateDocxContainer } from './docxAnnotations'
import type { DocumentAnalysisCitation } from '../../types'

describe('docxAnnotations', () => {
  it('highlights cited passages and attaches clickable numbered audit note pins to Word DOM', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <section class="docx">
        <h1>Financial Approval Matrix</h1>
        <p>Approval authority for procurement commitments. All amounts are stated in full PKR.</p>
        <table>
          <tr><td>Head of Treasury</td><td>1,000,000.00</td><td>PKR</td></tr>
          <tr><td>Chief Financial Officer (CFO)</td><td>10,000,000.00</td><td>PKR</td></tr>
        </table>
      </section>
    `

    const citations: DocumentAnalysisCitation[] = [
      { id: 'c1', page: 1, excerpt: 'Financial Approval Matrix', source_sha1: 'x' },
      { id: 'c5', page: 1, excerpt: '•  Chief Financial Officer (CFO)      10,000,000.00      PKR', source_sha1: 'x' },
    ]
    const onSelect = vi.fn()
    const result = annotateDocxContainer(root, {
      citations,
      notes: [
        { key: 'note:1', number: 1, text: 'Governance metadata not stated [c1].' },
        { key: 'note:2', number: 2, text: 'CFO/CEO boundary at PKR 10,000,000.00 needs clarification [c5].' },
      ],
      showCitations: true,
      showNotes: true,
      activeNoteKey: 'note:2',
      activeCitationId: null,
      onSelectNote: onSelect,
    })

    expect(result.citedCount).toBe(2)
    expect(result.noteCount).toBe(2)

    const pins = root.querySelectorAll<HTMLButtonElement>('button.aw-docx-pin')
    expect(pins).toHaveLength(2)
    expect(pins[0].textContent).toBe('1')
    expect(pins[1].textContent).toBe('2')
    expect(pins[1].classList.contains('active')).toBe(true)

    pins[0].click()
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ key: 'note:1', number: 1 }))
  })
})
