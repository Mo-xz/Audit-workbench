/**
 * Zip archives are unpacked here, in the browser, and never by the server.
 *
 * Only an archive's central directory is read up front. It carries every
 * entry's path, size and date, which is all the import manifest needs, so an
 * archive of any size is listed in milliseconds. An entry's bytes are inflated
 * only when the upload asks for them, one at a time: files the workspace
 * already holds unchanged are never inflated, and memory holds about one file
 * however large the archive is. Each inflated file then meets the server's
 * per-file upload limit and quota exactly as a loose file would.
 *
 * Entries land under a folder named after the archive — `Audit/FY24.zip`
 * becomes `Audit/FY24/…` — so re-importing an updated archive compares
 * against the files the last one brought in.
 */
import type { Entry, FileEntry } from '@zip.js/zip.js'
import type { StagedFile } from './useFileDrop'

/** Past this many files a drop is almost certainly a mistake, not an audit folder. */
export const MAX_ARCHIVE_ENTRIES = 50_000
/** A zip inside a zip inside a zip is unpacked; one more level is reported. */
export const MAX_ARCHIVE_DEPTH = 3

export interface ArchiveProblem {
  path: string
  reason: string
}

export interface ExpandedFiles {
  files: StagedFile[]
  problems: ArchiveProblem[]
  archives: number
}

export function isArchive(path: string): boolean {
  return /\.zip$/i.test(path)
}

type ZipModule = typeof import('@zip.js/zip.js')
let loading: Promise<ZipModule> | null = null

/** zip.js loads on the first archive, in its own chunk. */
function loadZip(): Promise<ZipModule> {
  loading ??= import('@zip.js/zip.js').then((zip) => {
    // The browser's own DecompressionStream does the inflating, so a worker
    // buys little, and running without one avoids worker/CSP surprises.
    zip.configure({ useWebWorkers: false, useCompressionStream: true })
    return zip
  })
  return loading
}

/** A zip entry's name as a safe relative path, or null when it is not one. */
export function entryPath(name: string): string | null {
  const parts = name.replace(/\\/g, '/').split('/').filter((part) => part !== '' && part !== '.')
  if (!parts.length || parts.includes('..') || /^[A-Za-z]:$/.test(parts[0])) return null
  return parts.join('/')
}

/** macOS adds resource forks to archives it creates; they are not the user's files. */
function isMacMetadata(path: string): boolean {
  const parts = path.split('/')
  return parts[0] === '__MACOSX' || parts[parts.length - 1].startsWith('._')
}

/**
 * Zipping a folder `FY24` gives `FY24.zip` whose entries all start `FY24/`.
 * Placed under the archive's folder that would read `FY24/FY24/…`, so a
 * single top folder named like the archive is dropped.
 */
function collapseRepeatedRoot(paths: string[], archiveName: string): string[] {
  const prefix = `${archiveName}/`
  return paths.length && paths.every((path) => path.startsWith(prefix))
    ? paths.map((path) => path.slice(prefix.length))
    : paths
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * Replace every `.zip` among `files` with the files inside it. Everything else
 * passes through untouched and in order. An archive that cannot be read, and
 * an entry that cannot be imported, is named in `problems` rather than failing
 * the batch.
 */
export async function expandArchives(
  files: StagedFile[],
  onArchive?: (path: string) => void,
): Promise<ExpandedFiles> {
  const out: StagedFile[] = []
  const problems: ArchiveProblem[] = []
  let archives = 0
  let entryCount = 0

  async function visit(file: StagedFile, depth: number): Promise<void> {
    if (!isArchive(file.relativePath)) {
      out.push(file)
      return
    }
    if (depth >= MAX_ARCHIVE_DEPTH) {
      problems.push({ path: file.relativePath, reason: `Archives nested more than ${MAX_ARCHIVE_DEPTH} deep are not unpacked.` })
      return
    }
    onArchive?.(file.relativePath)
    const zip = await loadZip()
    let entries: Entry[]
    try {
      const reader = new zip.ZipReader(new zip.BlobReader(await file.read()))
      // zip.js would reject the whole archive over one unsafe name. Every name
      // is checked below by `entryPath` instead, so a bad entry is named and
      // its siblings still import.
      entries = await reader.getEntries({ filenameValidation: 'tolerant' })
    } catch (error) {
      problems.push({ path: file.relativePath, reason: `Not a readable zip archive: ${message(error)}` })
      return
    }
    archives += 1
    const folder = file.relativePath.replace(/\.zip$/i, '')
    const archiveName = folder.split('/').pop() || folder

    const candidates: { entry: FileEntry; path: string }[] = []
    for (const entry of entries) {
      if (entry.directory) continue
      const path = entryPath(entry.filename)
      if (path === null) {
        problems.push({ path: `${file.relativePath}: ${entry.filename}`, reason: 'Unsafe path inside the archive.' })
        continue
      }
      if (isMacMetadata(path)) continue
      candidates.push({ entry, path })
    }
    const paths = collapseRepeatedRoot(candidates.map(({ path }) => path), archiveName)

    for (const [index, { entry }] of candidates.entries()) {
      entryCount += 1
      if (entryCount > MAX_ARCHIVE_ENTRIES) {
        throw new Error(`These archives hold more than ${MAX_ARCHIVE_ENTRIES.toLocaleString()} files. Import them in smaller parts.`)
      }
      const relativePath = `${folder}/${paths[index]}`
      if (entry.encrypted) {
        problems.push({ path: relativePath, reason: 'Password-protected inside the archive.' })
        continue
      }
      const modified = entry.lastModDate?.getTime()
      await visit({
        relativePath,
        size: entry.uncompressedSize,
        lastModified: Number.isFinite(modified) ? modified : 0,
        type: '',
        read: () => entry.getData(new zip.BlobWriter()),
      }, depth + 1)
    }
  }

  for (const file of files) await visit(file, 0)
  return { files: out, problems, archives }
}
