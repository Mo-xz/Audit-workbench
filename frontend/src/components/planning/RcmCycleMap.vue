<script setup lang="ts">
import { computed } from 'vue'

import type { CycleShape, RcmRow } from '../../types'
import { plural } from '../../format'

/**
 * Interactive end-to-end business-cycle risk strip above the RCM matrix.
 *
 * Reads the engagement's cycle stages (`planning.cycle.steps` + optional
 * `cross_cutting`) and projects the matrix's risks, severity heat, and Data vs.
 * Document test coverage onto each stage. Clicking any stage narrows the matrix
 * to that step; clicking it again returns to the full lifecycle.
 */

const props = defineProps<{
  cycle: CycleShape | null
  rows: RcmRow[]
  selectedProcess: string | null
}>()
const emit = defineEmits<{ select: [process: string | null] }>()

interface StageCard {
  name: string
  index: number | null
  crossCutting: boolean
  risks: number
  highCount: number
  ineffectiveCount: number
  dataTests: number
  docTests: number
  exceptions: number
  reviewedCount: number
  tone: 'bad' | 'warn' | 'ok' | 'neutral'
}

function countTestsByKind(rows: RcmRow[]): { dataTests: number; docTests: number } {
  let dataTests = 0
  let docTests = 0
  for (const row of rows) {
    const rollups = row.execution_rollup?.test_rollups ?? []
    if (rollups.length) {
      for (const r of rollups) {
        if (r.kind === 'datatest') dataTests += 1
        else if (r.kind === 'doctest') docTests += 1
      }
      continue
    }
    for (const ref of row.test_refs ?? []) {
      if (ref.startsWith('datatest:')) dataTests += 1
      else if (ref.startsWith('doctest:')) docTests += 1
    }
  }
  return { dataTests, docTests }
}

const stages = computed<StageCard[]>(() => {
  const byProcess = new Map<string, RcmRow[]>()
  for (const row of props.rows) {
    const key = String(row.process ?? '').trim() || 'Unassigned'
    const bucket = byProcess.get(key)
    if (bucket) bucket.push(row)
    else byProcess.set(key, [row])
  }

  const ordered: Array<{ name: string; index: number | null; crossCutting: boolean }> = []
  const seen = new Set<string>()

  if (props.cycle?.steps?.length) {
    props.cycle.steps.forEach((step, idx) => {
      const name = String(step.name ?? '').trim()
      if (!name || seen.has(name)) return
      seen.add(name)
      ordered.push({ name, index: idx + 1, crossCutting: false })
    })
  }
  const crossName = String(props.cycle?.cross_cutting?.name ?? '').trim()
  if (crossName && !seen.has(crossName) && byProcess.has(crossName)) {
    seen.add(crossName)
    ordered.push({ name: crossName, index: null, crossCutting: true })
  }
  for (const key of byProcess.keys()) {
    if (seen.has(key)) continue
    seen.add(key)
    ordered.push({
      name: key,
      index: props.cycle?.steps?.length ? null : ordered.length + 1,
      crossCutting: Boolean(props.cycle?.steps?.length),
    })
  }

  return ordered.map((entry) => {
    const bucket = byProcess.get(entry.name) ?? []
    const highCount = bucket.filter(r => r.risk_rating === 'high' || r.risk_rating === 'critical').length
    const ineffectiveCount = bucket.filter(r => r.execution_rollup?.control_conclusion === 'ineffective').length
    const exceptions = bucket.reduce((sum, r) => sum + (r.execution_rollup?.exceptions ?? 0), 0)
    const reviewedCount = bucket.filter(r => r.review_status === 'reviewed').length
    const { dataTests, docTests } = countTestsByKind(bucket)

    let tone: StageCard['tone'] = 'neutral'
    if (ineffectiveCount > 0 || exceptions > 0) tone = 'bad'
    else if (highCount > 0) tone = 'warn'
    else if (bucket.length > 0) tone = 'ok'

    return {
      ...entry,
      risks: bucket.length,
      highCount,
      ineffectiveCount,
      dataTests,
      docTests,
      exceptions,
      reviewedCount,
      tone,
    }
  })
})

const cycleTitle = computed(() => {
  const name = props.cycle?.name?.trim()
  const stepCount = stages.value.filter(s => !s.crossCutting).length
  if (name) return `${name} lifecycle · ${plural(stepCount, 'stage')}`
  return `Process lifecycle · ${plural(stages.value.length, 'stage')}`
})

function toggleStage(name: string) {
  emit('select', props.selectedProcess === name ? null : name)
}
</script>

<template>
  <section v-if="stages.length > 1" class="cycle-map" aria-label="Business cycle risk map">
    <header class="map-head">
      <div class="map-title">
        <i class="aw-icon aw-icon-shield" aria-hidden="true" />
        <strong>{{ cycleTitle }}</strong>
        <span class="map-hint">Click a stage to filter the matrix</span>
      </div>
      <button
        v-if="selectedProcess"
        type="button"
        class="clear-btn"
        @click="emit('select', null)"
      >
        <i class="aw-icon aw-icon-x" aria-hidden="true" />Show all stages
      </button>
    </header>

    <div class="stage-rail" role="list">
      <button
        v-for="stage in stages"
        :key="stage.name"
        type="button"
        role="listitem"
        class="stage-card"
        :class="{
          active: selectedProcess === stage.name,
          empty: stage.risks === 0,
          cross: stage.crossCutting,
        }"
        :data-tone="stage.tone"
        :aria-pressed="selectedProcess === stage.name"
        :title="stage.name"
        @click="toggleStage(stage.name)"
      >
        <div class="stage-top">
          <span class="stage-num" :class="{ cross: stage.crossCutting }">
            <template v-if="stage.index !== null">{{ stage.index }}</template>
            <i v-else class="aw-icon aw-icon-sparkles" aria-hidden="true" />
          </span>
          <span class="stage-count aw-figure">
            {{ plural(stage.risks, 'risk') }}
          </span>
          <span
            v-if="stage.exceptions > 0"
            class="heat-pill bad aw-figure"
          >
            {{ stage.exceptions }} exc
          </span>
          <span
            v-else-if="stage.highCount > 0"
            class="heat-pill warn aw-figure"
          >
            {{ stage.highCount }} high
          </span>
        </div>

        <span class="stage-name">{{ stage.name }}</span>

        <div class="stage-foot aw-figure">
          <span v-if="stage.dataTests > 0" class="kind-chip data">
            Data {{ stage.dataTests }}
          </span>
          <span v-if="stage.docTests > 0" class="kind-chip doc">
            Doc {{ stage.docTests }}
          </span>
          <span v-if="stage.dataTests === 0 && stage.docTests === 0 && stage.risks > 0" class="kind-chip none">
            No tests
          </span>
        </div>
      </button>
    </div>
  </section>
</template>

<style scoped>
.cycle-map {
  display: flex;
  flex-direction: column;
  gap: .5rem;
  min-width: 0;
  padding: .65rem .85rem .75rem;
  border: 1px solid var(--aw-border);
  border-radius: var(--aw-radius-surface);
  background: var(--aw-panel);
}

.map-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .6rem;
  flex-wrap: wrap;
}
.map-title {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  flex-wrap: wrap;
  color: var(--aw-ink-strong);
  font-size: var(--aw-text-xs);
}
.map-title .aw-icon { color: var(--aw-teal); font-size: var(--aw-text-sm); }
.map-hint { color: var(--aw-muted); font-weight: 500; }

.clear-btn {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .15rem .55rem;
  border: 1px solid var(--aw-teal-line);
  border-radius: var(--aw-radius-pill);
  background: var(--aw-teal-soft);
  color: var(--aw-teal-strong);
  font: inherit;
  font-size: var(--aw-text-2xs);
  font-weight: 600;
  cursor: pointer;
}
.clear-btn:hover { border-color: var(--aw-teal); }

.stage-rail {
  display: flex;
  gap: .5rem;
  overflow-x: auto;
  padding-bottom: .2rem;
  scrollbar-width: thin;
}

.stage-card {
  display: flex;
  flex-direction: column;
  gap: .35rem;
  flex: 0 0 11.75rem;
  min-width: 0;
  padding: .55rem .65rem;
  border: 1px solid var(--aw-border);
  border-top: 3px solid var(--aw-border-strong);
  border-radius: var(--aw-radius-control);
  background: var(--aw-canvas);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color .12s, background-color .12s, box-shadow .12s;
}
.stage-card[data-tone='bad'] { border-top-color: var(--aw-danger); }
.stage-card[data-tone='warn'] { border-top-color: var(--aw-warn); }
.stage-card[data-tone='ok'] { border-top-color: var(--aw-ok); }
.stage-card.cross { border-top-color: var(--aw-accent); }
.stage-card.empty { opacity: .65; }

.stage-card:hover:not(.active) {
  border-color: var(--aw-teal-line);
  background: var(--aw-raised);
}
.stage-card.active {
  border-color: var(--aw-teal);
  border-top-color: var(--aw-teal);
  background: var(--aw-teal-soft);
  box-shadow: 0 0 0 1px var(--aw-teal);
}
.stage-card:focus-visible { outline: 2px solid var(--aw-teal); outline-offset: 1px; }

.stage-top {
  display: flex;
  align-items: center;
  gap: .3rem;
}
.stage-num {
  display: grid;
  place-items: center;
  min-width: 1.15rem;
  height: 1.15rem;
  padding: 0 .2rem;
  border-radius: 50%;
  background: var(--aw-raised);
  color: var(--aw-ink-soft);
  font-size: var(--aw-text-2xs);
  font-weight: 700;
  flex: none;
}
.stage-num.cross {
  background: var(--aw-accent-soft);
  color: var(--aw-accent);
}
.stage-card.active .stage-num {
  background: var(--aw-teal);
  color: var(--aw-panel);
}
.stage-count {
  color: var(--aw-ink-strong);
  font-size: var(--aw-text-2xs);
  font-weight: 700;
}
.heat-pill {
  margin-left: auto;
  padding: .03rem .35rem;
  border-radius: var(--aw-radius-pill);
  font-size: var(--aw-text-2xs);
  font-weight: 700;
  white-space: nowrap;
}
.heat-pill.bad { background: var(--aw-danger-soft); color: var(--aw-danger); }
.heat-pill.warn { background: var(--aw-warn-soft); color: var(--aw-warn-ink); }

.stage-name {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--aw-ink);
  font-size: var(--aw-text-xs);
  font-weight: 600;
  line-height: 1.3;
  min-height: 2.6em;
}

.stage-foot {
  display: flex;
  align-items: center;
  gap: .3rem;
  flex-wrap: wrap;
  margin-top: auto;
}
.kind-chip {
  display: inline-flex;
  align-items: center;
  padding: .04rem .35rem;
  border-radius: var(--aw-radius-pill);
  font-size: var(--aw-text-2xs);
  font-weight: 600;
}
.kind-chip.data {
  background: var(--aw-teal-soft);
  color: var(--aw-teal-strong);
  border: 1px solid var(--aw-teal-line);
}
.kind-chip.doc {
  background: var(--aw-accent-soft);
  color: var(--aw-accent);
  border: 1px solid var(--aw-accent-line);
}
.kind-chip.none {
  background: var(--aw-raised);
  color: var(--aw-muted);
}
</style>
