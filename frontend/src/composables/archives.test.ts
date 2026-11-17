// @vitest-environment node
// zip.js reads through Blob streams and DecompressionStream, which Node has
// natively and jsdom's Blob does not.
import { describe, expect, it } from 'vitest'
import { BlobReader, BlobWriter, TextReader, ZipWriter, configure } from '@zip.js/zip.js'

import { entryPath, expandArchives } from './archives'
import type { StagedFile } from './useFileDrop'

configure({ useWebWorkers: false })

async function zipOf(entries: Record<string, string | Blob>, options: { password?: string } = {}): Promise<Blob> {
  const writer = new ZipWriter(new BlobWriter('application/zip'), options.password ? { password: options.password } : {})
  for (const [name, content] of Object.entries(entries)) {
    if (name.endsWith('/')) await writer.add(name, undefined, { directory: true })
    else await writer.add(name, typeof content === 'string' ? new TextReader(content) : new BlobReader(content))
  }
  return writer.close()
}

function staged(relativePath: string, blob: Blob): StagedFile {
  return { relativePath, size: blob.size, lastModified: 1, type: blob.type, read: () => Promise.resolve(blob) }
}

describe('expandArchives', () => {
  it('passes loose files through untouched and lists archive entries under the archive folder', async () => {
    const loose = staged('notes.txt', new Blob(['hello']))
    const archive = await zipOf({ 'invoices.csv': 'id,amount\n1,10\n', 'policies/': '', 'policies/travel.md': '# Travel' })
    const result = await expandArchives([loose, staged('Audit/FY24.zip', archive)])

    expect(result.archives).toBe(1)
    expect(result.problems).toEqual([])
    expect(result.files.map((file) => file.relativePath)).toEqual([
      'notes.txt',
      'Audit/FY24/invoices.csv',
      'Audit/FY24/policies/travel.md',
    ])
    expect(result.files[0]).toBe(loose)
    const invoices = result.files[1]
    expect(invoices.size).toBe('id,amount\n1,10\n'.length)
    expect(invoices.lastModified).toBeGreaterThan(0)
    expect(await (await invoices.read()).text()).toBe('id,amount\n1,10\n')
  })

  it('does not repeat a top folder named like the archive', async () => {
    const archive = await zipOf({ 'FY24/a.csv': 'x\n1\n', 'FY24/sub/b.csv': 'y\n2\n' })
    const result = await expandArchives([staged('FY24.zip', archive)])
    expect(result.files.map((file) => file.relativePath)).toEqual(['FY24/a.csv', 'FY24/sub/b.csv'])
  })

  it('unpacks nested archives and skips macOS metadata', async () => {
    const inner = await zipOf({ 'ledger.csv': 'a\n1\n' })
    const outer = await zipOf({ 'inner.zip': inner, '__MACOSX/._ledger.csv': 'junk', 'docs/._memo.pdf': 'junk', 'docs/memo.txt': 'memo' })
    const result = await expandArchives([staged('outer.zip', outer)])
    expect(result.archives).toBe(2)
    expect(result.files.map((file) => file.relativePath)).toEqual(['outer/inner/ledger.csv', 'outer/docs/memo.txt'])
  })

  it('names an entry whose path escapes the archive and still imports its siblings', async () => {
    const archive = await zipOf({ 'ok.csv': 'a\n1\n', '../evil.csv': 'b\n2\n' })
    const result = await expandArchives([staged('mixed.zip', archive)])
    expect(result.files.map((file) => file.relativePath)).toEqual(['mixed/ok.csv'])
    expect(result.problems).toEqual([{ path: 'mixed.zip: ../evil.csv', reason: 'Unsafe path inside the archive.' }])
  })

  it('names an unreadable archive and a password-protected entry instead of failing', async () => {
    const locked = await zipOf({ 'secret.csv': 'a\n1\n' }, { password: 'pw' })
    const result = await expandArchives([
      staged('broken.zip', new Blob(['not a zip at all'])),
      staged('locked.zip', locked),
    ])
    expect(result.files).toEqual([])
    expect(result.problems.map((problem) => problem.path)).toEqual(['broken.zip', 'locked/secret.csv'])
    expect(result.problems[1].reason).toMatch(/Password-protected/)
  })
})

describe('entryPath', () => {
  it('normalises separators and refuses paths that escape the archive', () => {
    expect(entryPath('a\\b\\c.csv')).toBe('a/b/c.csv')
    expect(entryPath('/abs/./x.csv')).toBe('abs/x.csv')
    expect(entryPath('../evil.csv')).toBeNull()
    expect(entryPath('ok/../../evil.csv')).toBeNull()
    expect(entryPath('C:/windows/x.csv')).toBeNull()
    expect(entryPath('')).toBeNull()
  })
})
