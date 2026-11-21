import type { DocumentAnalysisCitation } from '../../types'

export interface DocxNoteInput {
  key: string
  number: number
  text: string
}

export interface DocxAnnotationResult {
  citedCount: number
  noteCount: number
  elementByNoteKey: Map<string, HTMLElement>
  elementByCitationId: Map<string, HTMLElement>
}

function normalize(value: string): string {
  return value
    .replace(/[•·▪◦–—]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function significantTokens(value: string): string[] {
  return normalize(value)
    .replace(/[^a-z0-9., ]+/g, ' ')
    .split(/\s+/)
    .filter(token => token.length >= 3)
}

function blockCandidates(container: HTMLElement): HTMLElement[] {
  const nodes = Array.from(
    container.querySelectorAll<HTMLElement>('section.docx tr, section.docx li, section.docx p, section.docx h1, section.docx h2, section.docx h3, section.docx h4'),
  )
  if (nodes.length) return nodes
  return Array.from(container.querySelectorAll<HTMLElement>('tr, li, p, h1, h2, h3, h4'))
}

function findBestBlock(blocks: Array<{ el: HTMLElement; text: string }>, query: string): HTMLElement | null {
  const needle = normalize(query)
  if (needle.length < 3) return null

  // 1. Exact substring match, preferring the most specific (shortest) block
  let best: { el: HTMLElement; len: number } | null = null
  for (const block of blocks) {
    if (block.text.includes(needle)) {
      if (!best || block.text.length < best.len) {
        best = { el: block.el, len: block.text.length }
      }
    }
  }
  if (best) return best.el

  // 2. Prefix match (first 48 chars) for long citations that wrap across elements
  if (needle.length > 48) {
    const head = needle.slice(0, 48).trim()
    for (const block of blocks) {
      if (block.text.includes(head)) return block.el
    }
  }

  // 3. Token-overlap match (handles table rows where Word separates columns across cells)
  const tokens = significantTokens(needle)
  if (tokens.length >= 2) {
    let bestScore = 0
    let bestEl: HTMLElement | null = null
    for (const block of blocks) {
      let hits = 0
      for (const token of tokens) {
        if (block.text.includes(token)) hits += 1
      }
      const ratio = hits / tokens.length
      if (ratio >= 0.75 && hits >= 2 && (ratio > bestScore || (ratio === bestScore && bestEl && block.text.length < (bestEl.textContent?.length ?? Infinity)))) {
        bestScore = ratio
        bestEl = block.el
      }
    }
    if (bestEl) return bestEl
  }
  return null
}

function noteSearchQueries(noteText: string): string[] {
  const out: string[] = []
  for (const match of noteText.matchAll(/["\u201c]([^"\u201d]{3,90})["\u201d]/g)) {
    out.push(match[1])
  }
  for (const match of noteText.matchAll(/(?<![A-Za-z0-9])['\u2018]([^'\u2019]{3,90})['\u2019]/g)) {
    out.push(match[1])
  }
  for (const match of noteText.matchAll(/\b(?:PKR\s?[\d,.]+|[A-Z]{2,6}[-]?\d{4,}[-A-Z0-9]*)\b/g)) {
    out.push(match[0])
  }
  return out
}

export function clearDocxAnnotations(container: HTMLElement): void {
  container.querySelectorAll('.aw-docx-pin').forEach(el => el.remove())
  container.querySelectorAll('.aw-docx-cited, .aw-docx-cited-active, .aw-docx-note-host, .aw-docx-note-active').forEach(el => {
    el.classList.remove('aw-docx-cited', 'aw-docx-cited-active', 'aw-docx-note-host', 'aw-docx-note-active')
    el.removeAttribute('data-aw-citation-id')
  })
}

export function annotateDocxContainer(
  container: HTMLElement,
  options: {
    citations: DocumentAnalysisCitation[]
    notes: DocxNoteInput[]
    showCitations: boolean
    showNotes: boolean
    activeNoteKey: string | null
    activeCitationId: string | null
    onSelectNote: (note: DocxNoteInput) => void
  },
): DocxAnnotationResult {
  clearDocxAnnotations(container)

  const rawBlocks = blockCandidates(container)
  const blocks = rawBlocks
    .map(el => ({ el, text: normalize(el.textContent || '') }))
    .filter(item => item.text.length > 0)

  const elementByCitationId = new Map<string, HTMLElement>()
  const elementByNoteKey = new Map<string, HTMLElement>()

  // 1. Locate & highlight AI citations
  for (const citation of options.citations) {
    const excerpt = (citation.excerpt || '').trim()
    if (!excerpt) continue
    const el = findBestBlock(blocks, excerpt)
    if (!el) continue
    elementByCitationId.set(citation.id, el)
    if (options.showCitations || options.activeCitationId === citation.id) {
      el.classList.add('aw-docx-cited')
      el.setAttribute('data-aw-citation-id', citation.id)
      if (options.activeCitationId === citation.id) {
        el.classList.add('aw-docx-cited-active')
      }
    }
  }

  // 2. Locate & attach amber numbered pins for audit notes
  for (const note of options.notes) {
    let target: HTMLElement | null = null
    for (const match of note.text.matchAll(/\[(c\d+)\]/g)) {
      const cited = elementByCitationId.get(match[1])
      if (cited) { target = cited; break }
    }
    if (!target) {
      for (const query of noteSearchQueries(note.text)) {
        const found = findBestBlock(blocks, query)
        if (found) { target = found; break }
      }
    }
    if (!target && blocks.length) {
      target = blocks[0].el
    }
    if (!target) continue

    elementByNoteKey.set(note.key, target)
    if (!options.showNotes && options.activeNoteKey !== note.key) continue

    const isActive = options.activeNoteKey === note.key
    target.classList.add('aw-docx-note-host')
    if (isActive) target.classList.add('aw-docx-note-active')

    // Keep table markup valid: attach inside the last cell when host is a <tr>
    const mountHost = target.tagName === 'TR'
      ? (target.querySelector<HTMLElement>('td:last-child, th:last-child') ?? target)
      : target

    const pin = document.createElement('button')
    pin.type = 'button'
    pin.className = isActive ? 'aw-docx-pin active' : 'aw-docx-pin'
    pin.dataset.noteKey = note.key
    pin.textContent = String(note.number)
    pin.setAttribute('aria-label', `Audit note ${note.number}: ${note.text}`)
    pin.setAttribute('aria-expanded', String(isActive))
    pin.title = `Audit note #${note.number} — click to read`
    pin.addEventListener('click', event => {
      event.stopPropagation()
      options.onSelectNote(note)
    })
    mountHost.appendChild(pin)
  }

  return {
    citedCount: elementByCitationId.size,
    noteCount: elementByNoteKey.size,
    elementByNoteKey,
    elementByCitationId,
  }
}
