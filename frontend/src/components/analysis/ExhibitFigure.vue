<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../../api'
import type { AnalysisDetail, AnalysisExceptions, SavedAnalysis } from '../../types'
import { classificationTone, foundSummary } from './analysisStatus'
import MemoExhibitBody from './MemoExhibitBody.vue'
import type { Embed } from './memoExhibits'

/**
 * One analysis exhibit standing on its own, outside the memo that numbers
 * and loads its exhibits together: the planning memorandum carries the memo's
 * analytics section, and draws each embed it holds through this. It fetches
 * only what its embed needs — a chart or table wants the result, a table of
 * flagged rows wants the rows.
 */
const props = defineProps<{
  workspaceId: string
  embed: Embed
  number: number
  analysis?: SavedAnalysis
}>()
const emit = defineEmits<{ open: [analysisId: string] }>()

const detail = ref<AnalysisDetail>()
const flagged = ref<AnalysisExceptions>()
const failed = ref(false)

async function load() {
  const base = `/api/workspaces/${props.workspaceId}/analyses/${props.embed.analysis}`
  failed.value = false
  try {
    if (props.embed.as === 'exception_table') flagged.value = await api.get<AnalysisExceptions>(`${base}/exceptions`)
    else if (props.embed.as !== 'stats') detail.value = await api.get<AnalysisDetail>(base)
  } catch {
    failed.value = true
  }
}
watch(() => [props.workspaceId, props.embed.analysis, props.embed.as], () => void load(), { immediate: true })

const title = computed(() => props.analysis?.title || props.embed.analysis)
const found = computed(() => (props.analysis ? foundSummary(props.analysis) : ''))
const tone = computed(() => (props.analysis ? classificationTone(props.analysis.classification) : 'neutral'))
</script>

<template>
  <figure class="exhibit" :data-exhibit-number="number">
    <button type="button" class="exhibit-head" @click="emit('open', embed.analysis)">
      <span class="exhibit-no">Exhibit {{ number }}</span>
      <span class="exhibit-title">{{ title }}</span>
      <span v-if="found" class="exhibit-found" :data-tone="tone">{{ found }}</span>
      <span class="exhibit-id">{{ embed.analysis }}</span>
    </button>
    <MemoExhibitBody
      :embed="embed"
      :number="number"
      :analysis="analysis"
      :detail="detail"
      :flagged="flagged"
      :failed="failed"
    />
  </figure>
</template>

<style scoped>
.exhibit {
  margin: 1.125rem 0 1.25rem;
  border: 1px solid var(--aw-border); border-radius: 6px;
  overflow: hidden;
  font-family: var(--aw-font-sans);
  break-inside: avoid;
}
.exhibit-head {
  display: flex; flex-wrap: wrap; align-items: center; gap: .375rem .75rem;
  width: 100%; padding: .55rem .875rem;
  border: 0; border-bottom: 1px solid var(--aw-border); background: var(--aw-raised);
  color: inherit; font: inherit; text-align: left; cursor: pointer;
}
.exhibit-head:hover .exhibit-title { text-decoration: underline; }
.exhibit-no { color: var(--aw-teal); font-size: var(--aw-text-xs); font-weight: 700; white-space: nowrap; }
.exhibit-title { flex: 1 1 12rem; min-width: 0; color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-weight: 650; line-height: 1.35; }
.exhibit-found {
  padding: 0 .5rem;
  border: 1px solid var(--aw-border-strong); border-radius: var(--aw-radius-pill);
  color: var(--aw-ink-soft); font-size: var(--aw-text-2xs); font-weight: 600; white-space: nowrap;
}
.exhibit-found[data-tone='bad'] { border-color: var(--aw-danger-line); background: var(--aw-danger-soft); color: var(--aw-danger-ink); }
.exhibit-found[data-tone='warn'] { border-color: var(--aw-warn-line); background: var(--aw-warn-soft); color: var(--aw-warn-ink); }
.exhibit-found[data-tone='ok'] { border-color: var(--aw-ok-line); background: var(--aw-ok-soft); color: var(--aw-ok); }
.exhibit-id { color: var(--aw-teal); font-family: var(--aw-font-mono); font-size: var(--aw-text-2xs); white-space: nowrap; }
</style>
