<script setup lang="ts">
/**
 * Choose or drop files, and they import. One action, no confirmation.
 *
 * There used to be a Review step between upload and completion, where an
 * auditor set each file's route, name and *document category*. Only the last of
 * those was ever a judgement, and it was being made from a filename — which is
 * the one input that cannot settle it. What a document is to this engagement is
 * now read from its opening page by `documents.categorized`, after import, and
 * shows in the Record spine as Document classification. A staging step outlived
 * it, asking the auditor to confirm a selection they had just made; that is gone
 * too, so choosing or dropping files is the import.
 *
 * What the review step also carried, and what happens to it now: the route is
 * deterministic on the file suffix and reported in the summary; the name is a
 * slug, renameable where documents are listed; duplicates are already left out
 * automatically. The one thing it surfaced that nothing else did is a file the
 * local parser could not read, and those are named in the summary rather than
 * folded into a count.
 *
 * Zip archives are unpacked here, in the browser, an entry at a time as the
 * upload asks for it (`composables/archives.ts`). The server never sees one.
 */
import { computed, ref, watch } from 'vue'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'

import { api } from '../api'
import { useAgentRun } from '../composables/useAgentRun'
import { collectDroppedFiles, stagedFromFile, type StagedFile } from '../composables/useFileDrop'
import { expandArchives, isArchive, type ArchiveProblem } from '../composables/archives'
import type { IntakeBatch } from '../types'
import PostImportPlanningOffer from './PostImportPlanningOffer.vue'

const props = defineProps<{ workspaceId: string; modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  imported: []
  'planning-started': []
}>()
const agent = useAgentRun(props.workspaceId)
const { launchMode } = agent

type Phase = 'idle' | 'reading' | 'uploading' | 'complete'

const phase = ref<Phase>('idle')
const dragActive = ref(false)
const batch = ref<IntakeBatch | null>(null)
const error = ref('')
const uploaded = ref(0)
const readingArchive = ref('')
const archiveProblems = ref<ArchiveProblem[]>([])
const archiveCount = ref(0)
const filePicker = ref<HTMLInputElement | null>(null)

const busy = computed(() => phase.value === 'reading' || phase.value === 'uploading')
const uploadTotal = computed(() => batch.value?.items.filter((item) => item.needs_upload).length ?? 0)
const progress = computed(() => uploadTotal.value ? Math.round(uploaded.value / uploadTotal.value * 100) : 100)
const uploadedItems = computed(() => batch.value?.items.filter((item) => item.uploaded) ?? [])
/** Files that could not be read — by the local parser or out of an archive. Named, never counted. */
const unreadable = computed(() => [
  ...uploadedItems.value
    .filter((item) => item.error || item.classification?.route === 'unsupported')
    .map((item) => ({
      key: item.id,
      path: item.relative_path,
      reason: item.error || item.classification?.rationale || '',
    })),
  ...archiveProblems.value.map((problem) => ({ key: problem.path, ...problem })),
])
const routeCounts = computed(() => {
  const counts = { table: 0, document: 0, excluded: 0 }
  for (const item of uploadedItems.value) {
    const classification = item.classification
    if (!classification || classification.proposed_action === 'ignore'
      || classification.route === 'ignore' || classification.route === 'unsupported') {
      counts.excluded += 1
    } else if (classification.route === 'table') {
      counts.table += 1
    } else if (classification.route === 'document') {
      counts.document += 1
    }
  }
  return counts
})
const planningAction = computed(() => (
  batch.value?.suggested_actions?.find(action => action.agent_kind === 'planning') ?? null
))

watch(() => props.modelValue, (open) => {
  if (!open) return
  if (!agent.state.status) void agent.refreshStatus()
  // A finished batch stays visible until close; reopening starts fresh.
  if (phase.value === 'complete') reset()
})

/**
 * Everything from a single dropped/selected folder or archive keeps that
 * folder as its incremental source; loose files and mixed batches share
 * "Direct uploads".
 */
function rootName(files: StagedFile[]): string {
  const roots = new Set(files.map(({ relativePath }) => relativePath.includes('/') ? relativePath.split('/')[0] : ''))
  return roots.size === 1 ? [...roots][0] : ''
}

/** Opens the system file picker straight away; choosing is importing. */
function pickFiles() {
  if (busy.value) return
  filePicker.value?.click()
}

defineExpose({ importFiles, pickFiles })

/** Enter and Space open the file picker the label wraps. */
function activatePicker(event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  ;(event.currentTarget as HTMLElement).querySelector('input')?.click()
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? []).map((file) => stagedFromFile(file))
  input.value = ''
  void importFiles(files)
}

function chooseFolder(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? []).map((file) => stagedFromFile(file, relativePath(file)))
  input.value = ''
  void importFiles(files)
}

async function onDrop(event: DragEvent) {
  dragActive.value = false
  if (busy.value) return
  void importFiles(await collectDroppedFiles(event))
}

function relativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
}

function fileName(path: string): string {
  return path.split('/').pop() || path
}

/** Later entries win: a folder and an archive that unpack to the same path must not both reach the manifest. */
function unique(files: StagedFile[]): StagedFile[] {
  return [...new Map(files.map((file) => [file.relativePath, file])).values()]
}

async function upload(file: StagedFile, batchId: string) {
  const blob = await file.read()
  const body = blob instanceof File
    ? blob
    : new File([blob], fileName(file.relativePath), { lastModified: file.lastModified, type: file.type })
  await api.uploadOne(
    `/api/workspaces/${props.workspaceId}/folder-imports/${batchId}/files`,
    body,
    { relative_path: file.relativePath },
  )
}

async function importFiles(selected: StagedFile[]) {
  if (!selected.length || busy.value) return
  reset()
  emit('update:modelValue', true)
  try {
    let files = selected
    if (selected.some((file) => isArchive(file.relativePath))) {
      phase.value = 'reading'
      const expanded = await expandArchives(selected, (path) => { readingArchive.value = fileName(path) })
      files = expanded.files
      archiveProblems.value = expanded.problems
      archiveCount.value = expanded.archives
    }
    files = unique(files)
    if (!files.length) {
      phase.value = 'complete'
      return
    }
    phase.value = 'uploading'
    const manifest = files.map((file) => ({
      relative_path: file.relativePath,
      size: file.size,
      last_modified: file.lastModified,
      mime: file.type,
    }))
    const compared = await api.post<{ batch: IntakeBatch; upload_paths: string[] }>(
      `/api/workspaces/${props.workspaceId}/folder-imports`,
      { root_name: rootName(files), manifest, mode: launchMode.value },
    )
    batch.value = compared.batch
    const requested = new Set(compared.upload_paths)
    // One file at a time: an archive entry is inflated only here, and released
    // before the next, so memory holds about one file.
    for (const file of files) {
      if (!requested.has(file.relativePath)) continue
      await upload(file, batch.value.id)
      uploaded.value += 1
    }
    batch.value = await api.post<IntakeBatch>(
      `/api/workspaces/${props.workspaceId}/folder-imports/${batch.value.id}/complete-upload`,
    )
    // Nothing left to decide: routing is settled by the suffix and the category
    // is read after import. Apply immediately rather than staging a review of
    // answers the auditor cannot usefully change.
    batch.value = await api.post<IntakeBatch>(
      `/api/workspaces/${props.workspaceId}/folder-imports/${batch.value.id}/apply`,
      { decisions: [] },
    )
    phase.value = 'complete'
    emit('imported')
  } catch (cause) {
    const failed = batch.value
    reset()
    error.value = cause instanceof Error ? cause.message : String(cause)
    if (failed?.status === 'uploading') {
      try {
        await api.del(`/api/workspaces/${props.workspaceId}/folder-imports/${failed.id}`)
      } catch {
        /* A later selection creates a fresh durable batch. */
      }
    }
  }
}

function close() {
  if (busy.value) return
  emit('update:modelValue', false)
}

function reset() {
  phase.value = 'idle'
  batch.value = null
  uploaded.value = 0
  error.value = ''
  readingArchive.value = ''
  archiveProblems.value = []
  archiveCount.value = 0
}
</script>

<template>
  <!-- Outside the dialog so `pickFiles` works while it is closed: the picker
       opens first, and the dialog only once there is something to show. -->
  <input ref="filePicker" class="hidden-picker" type="file" multiple tabindex="-1" aria-hidden="true" @change="chooseFiles" />
  <Dialog :visible="modelValue" modal header="Import files" class="folder-import-dialog" :style="{ width: 'min(94vw, 46rem)' }" :closable="!busy" @update:visible="close">
    <div
      class="import-body"
      :class="{ 'drag-active': dragActive && !busy }"
      @dragover.prevent="dragActive = !busy"
      @dragleave.prevent="dragActive = false"
      @drop.prevent="onDrop"
    >
      <div v-if="error" class="inline-error"><i class="aw-icon aw-icon-triangle-alert" />{{ error }}</div>

      <section v-if="phase === 'idle'" class="dropzone" :class="{ active: dragActive }">
        <i class="aw-icon aw-icon-cloud-upload" />
        <strong>Drop files, a folder or a zip archive here</strong>
        <span>They import as soon as they are chosen. Spreadsheets and CSVs become data tables; PDFs, Word files and images become documents; zip archives are unpacked first. Unchanged files are skipped.</span>
        <div class="picker-actions">
          <label class="picker-button" tabindex="0" @keydown="activatePicker">
            <i class="aw-icon aw-icon-file" />Choose files
            <input type="file" multiple @change="chooseFiles" />
          </label>
          <label class="picker-button" tabindex="0" @keydown="activatePicker">
            <i class="aw-icon aw-icon-folder-open" />Choose a folder
            <input type="file" webkitdirectory multiple @change="chooseFolder" />
          </label>
        </div>
      </section>

      <section v-else-if="phase === 'reading'" class="progress-step" aria-live="polite">
        <h3>Reading archive</h3>
        <ProgressBar mode="indeterminate" class="indeterminate" />
        <p class="muted">{{ readingArchive || 'Listing the files inside…' }}</p>
      </section>

      <section v-else-if="phase === 'uploading'" class="progress-step" aria-live="polite">
        <h3>Importing</h3>
        <ProgressBar :value="progress" />
        <p class="muted">{{ uploaded }} of {{ uploadTotal }} file{{ uploadTotal === 1 ? '' : 's' }} uploaded.</p>
      </section>

      <section v-else class="summary-step">
        <h3>Import complete</h3>
        <div class="route-summary" aria-label="What was imported">
          <span><i class="aw-icon aw-icon-table" /><strong>{{ routeCounts.table }}</strong> data {{ routeCounts.table === 1 ? 'table' : 'tables' }}</span>
          <span><i class="aw-icon aw-icon-file" /><strong>{{ routeCounts.document }}</strong> {{ routeCounts.document === 1 ? 'document' : 'documents' }}</span>
          <span><i class="aw-icon aw-icon-circle-minus" /><strong>{{ routeCounts.excluded }}</strong> left out</span>
        </div>
        <div class="summary-cards" v-if="batch?.summary || archiveCount">
          <template v-if="batch?.summary">
            <span><strong>{{ batch.summary.imported }}</strong> imported</span>
            <span><strong>{{ batch.summary.unchanged }}</strong> unchanged</span>
            <span><strong>{{ batch.summary.ignored }}</strong> ignored</span>
          </template>
          <span v-if="archiveCount"><strong>{{ archiveCount }}</strong> zip {{ archiveCount === 1 ? 'archive' : 'archives' }} unpacked</span>
        </div>
        <div v-if="unreadable.length" class="unreadable">
          <i class="aw-icon aw-icon-triangle-alert" />
          <span>
            <strong>{{ unreadable.length }} file{{ unreadable.length === 1 ? '' : 's' }} could not be read and {{ unreadable.length === 1 ? 'was' : 'were' }} left out</strong>
            <small v-for="item in unreadable" :key="item.key">
              {{ fileName(item.path) }}<template v-if="item.reason"> — {{ item.reason }}</template>
            </small>
          </span>
        </div>
        <div v-if="batch?.indexing_job?.document_ids.length" class="selection-summary">
          <i class="aw-icon aw-icon-spin aw-icon-loader-circle" />
          <span><strong>Search indexing continues in the background</strong><small>{{ batch.indexing_job.document_ids.length }} imported document{{ batch.indexing_job.document_ids.length === 1 ? '' : 's' }} will become searchable automatically.</small></span>
        </div>
        <PostImportPlanningOffer
          v-if="planningAction"
          :workspaceId="workspaceId"
          :action="planningAction"
          @planning-started="emit('planning-started'); close()"
        />
        <div class="review-actions"><Button label="Import more" severity="secondary" @click="pickFiles" /><Button label="Done" @click="close" /></div>
      </section>
    </div>
  </Dialog>
</template>

<style scoped>
.hidden-picker { position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.import-body { display: grid; gap: 1rem; border-radius: var(--aw-radius-surface); transition: outline-color .15s; outline: 2px dashed transparent; outline-offset: .35rem; }
.import-body.drag-active { outline-color: var(--aw-teal); }
.dropzone { display: flex; flex-direction: column; align-items: center; gap: .45rem; padding: 2.2rem 1.5rem; border: 2px dashed var(--aw-border-strong); border-radius: var(--aw-radius-surface); background: var(--aw-canvas); text-align: center; transition: border-color .15s, background .15s; }
.dropzone.active { border-color: var(--aw-teal); background: var(--aw-teal-soft); }
.dropzone > i { font-size: var(--aw-text-3xl); color: var(--aw-teal); }
.dropzone > span { max-width: 32rem; color: var(--aw-muted); font-size: var(--aw-text-sm); }
.picker-actions { display: flex; gap: .65rem; margin-top: .7rem; flex-wrap: wrap; justify-content: center; }
.picker-button { position: relative; display: inline-flex; align-items: center; gap: .45rem; padding: .5rem .95rem; border: 1px solid var(--aw-border-strong); border-radius: var(--aw-radius-control); background: var(--aw-panel); font-size: var(--aw-text-sm); font-weight: 600; cursor: pointer; transition: border-color .15s, color .15s; }
.picker-button:hover { border-color: var(--aw-teal); color: var(--aw-teal); }
.picker-button i { color: var(--aw-teal); }
.picker-button input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.selection-summary { display: flex; align-items: center; gap: .65rem; padding: .7rem .85rem; border: 1px solid var(--aw-teal-line); border-radius: var(--aw-radius-control); background: var(--aw-teal-soft); }
.selection-summary > i { color: var(--aw-teal); }
.selection-summary span { display: grid; gap: .15rem; }
.selection-summary small { color: var(--aw-muted); }
.unreadable { display: flex; gap: .65rem; padding: .7rem .85rem; border: 1px solid var(--aw-warn-line, var(--aw-border-strong)); border-radius: var(--aw-radius-control); background: var(--aw-warn-soft, var(--aw-raised)); }
.unreadable > i { color: var(--aw-danger); }
.unreadable span { display: grid; gap: .15rem; min-width: 0; }
.unreadable small { color: var(--aw-muted); overflow-wrap: anywhere; }
.inline-error { display: flex; gap: .45rem; padding: .65rem; color: var(--aw-danger); background: var(--aw-danger-soft); border-radius: var(--aw-radius-control); }
.progress-step { margin: 2rem 0; text-align: center; }
.indeterminate { height: .4rem; }
.muted { color: var(--aw-muted); font-size: var(--aw-text-sm); overflow-wrap: anywhere; }
.summary-step { display: grid; gap: 1rem; }
.summary-cards { display: flex; gap: 1.2rem; flex-wrap: wrap; color: var(--aw-muted); font-size: var(--aw-text-sm); }
.summary-cards strong { color: var(--aw-ink); font-size: var(--aw-text-base); }
.route-summary { display: flex; gap: 1.2rem; flex-wrap: wrap; color: var(--aw-muted); font-size: var(--aw-text-sm); }
.route-summary i { margin-right: .35rem; color: var(--aw-teal); }
.route-summary strong { color: var(--aw-ink); }
.review-actions { display: flex; gap: .6rem; justify-content: flex-end; align-items: center; }
</style>
