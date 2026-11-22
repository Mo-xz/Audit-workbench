<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
import SplitButton from 'primevue/splitbutton'
import type { MenuItem } from 'primevue/menuitem'

import { useWorkspaceNav } from '../../composables/useWorkspaceNavigation'
import { plural } from '../../format'
import type { EngagementOpenPoint, EngagementStage } from '../../types'
import UiStateIcon from '../ui/UiStateIcon.vue'
import type { RecordPhaseGroup, RecordStageItem, RecordStartRequest } from './recordViewModel'

defineProps<{
  groups: RecordPhaseGroup[]
  starting: string
}>()

const emit = defineEmits<{
  start: [stage: EngagementStage, alternate?: RecordStartRequest]
  'open-point': [point: EngagementOpenPoint]
}>()

const nav = useWorkspaceNav()

function startOptions(stage: EngagementStage): MenuItem[] {
  return (stage.start?.alternates ?? []).map(alternate => ({
    label: alternate.label,
    note: alternate.note,
    command: () => emit('start', stage, alternate),
  }))
}

function visibleFacts(item: RecordStageItem) {
  return item.facts.filter(f => f.kind !== 'owed' && f.kind !== 'tool')
}

function toolFacts(item: RecordStageItem) {
  return item.facts.filter(f => f.kind === 'tool')
}
</script>

<template>
  <section class="board" aria-label="Audit board by phase" data-testid="record-board">
    <section
      v-for="group in groups"
      :key="group.id"
      class="col"
      :data-state="group.live ? 'live' : group.state"
    >
      <header class="col-head">
        <span class="col-num" aria-hidden="true">{{ group.index + 1 }}</span>
        <div class="col-copy">
          <h3>{{ group.title }}</h3>
          <span class="col-sub">
            <span class="col-status">{{ group.statusLabel }}</span>
            <span v-if="group.openPoints" class="col-gate">{{ plural(group.openPoints, 'review') }}</span>
          </span>
        </div>
      </header>

      <div class="col-track" aria-hidden="true">
        <i :style="{ width: `${Math.round(group.fill * 100)}%` }" />
      </div>

      <div class="cards">
        <article
          v-for="item in group.items"
          :key="item.stage.id"
          class="card"
          :class="{ ghost: !item.stage.held, lead: item.isLead }"
          :data-live="item.live || null"
        >
          <div class="card-top">
            <component
              :is="item.destination ? RouterLink : 'span'"
              :to="item.destination ? nav.to(item.destination) : undefined"
              class="card-title"
              :class="{ linked: Boolean(item.destination) }"
            >{{ item.stage.filed?.label || item.stage.capability }}</component>
            <span v-if="item.live" class="live-dot" aria-hidden="true" />
            <UiStateIcon v-else class="state-ico" :state="item.state" />
          </div>

          <div v-if="visibleFacts(item).length" class="card-facts">
            <template v-for="(fact, idx) in visibleFacts(item)" :key="`${fact.kind}:${idx}`">
              <span v-if="idx" class="sep" aria-hidden="true">·</span>
              <component
                :is="fact.to ? RouterLink : 'span'"
                :to="fact.to ? nav.to(fact.to) : undefined"
                :class="fact.to ? 'door' : fact.kind"
              ><b v-if="fact.figure">{{ fact.figure }}</b>{{ fact.figure ? ' ' : '' }}{{ fact.text }}<template
                v-for="(part, at) in fact.parts ?? []"
                :key="part.text"
              >{{ at ? ', ' : fact.text ? ' ' : '' }}<b :data-severity="part.severity || null">{{ part.figure }}</b> {{ part.text }}</template></component>
            </template>
          </div>

          <p v-if="item.attentionReason" class="card-warn">{{ item.attentionReason }}</p>

          <div v-if="item.live" class="card-live">
            <i :class="item.live === 'running' ? 'aw-icon aw-icon-spin aw-icon-loader-circle' : 'aw-icon aw-icon-clock'" aria-hidden="true" />
            <span>{{ item.live === 'running' ? (item.stage.held ? 'Running again' : 'Running now') : 'Queued' }}<template v-if="item.liveElapsed"> · {{ item.liveElapsed }}</template></span>
          </div>

          <button
            v-for="point in item.stage.open_points"
            :key="point.key"
            type="button"
            class="card-open"
            @click="emit('open-point', point)"
          >
            <span class="open-msg">{{ point.message }}</span>
            <span class="open-go">{{ point.action }} <i class="aw-icon aw-icon-arrow-right" aria-hidden="true" /></span>
          </button>

          <div
            v-if="item.isLead || item.stage.action === 'import' || toolFacts(item).length"
            class="card-foot"
          >
            <template v-for="tool in toolFacts(item)" :key="tool.text">
              <RouterLink v-if="tool.to" :to="nav.to(tool.to)" class="tool-link">
                <i class="aw-icon aw-icon-wrench" aria-hidden="true" />{{ tool.text }}
              </RouterLink>
            </template>
            <span class="grow" />
            <Button
              v-if="item.stage.action === 'import' && item.isLead"
              label="Import"
              size="small"
              @click="emit('start', item.stage)"
            />
            <button
              v-else-if="item.stage.action === 'import'"
              type="button"
              class="text-act"
              @click="emit('start', item.stage)"
            >{{ item.stage.held ? 'Import more' : 'Import' }}</button>
            <SplitButton
              v-else-if="item.isLead && item.stage.start?.alternates.length"
              label="Run"
              size="small"
              :disabled="starting === item.stage.capability"
              :model="startOptions(item.stage)"
              @click="emit('start', item.stage)"
            />
            <Button
              v-else-if="item.isLead"
              label="Run"
              size="small"
              :loading="starting === item.stage.capability"
              @click="emit('start', item.stage)"
            />
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .75rem;
  align-items: start;
}

.col {
  display: flex; flex-direction: column; gap: .625rem; min-width: 0;
  padding: .75rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-surface);
  background: color-mix(in srgb, var(--aw-raised) 55%, var(--aw-panel));
}
.col[data-state='current'] {
  border-color: var(--aw-teal-line);
  background: color-mix(in srgb, var(--aw-teal-soft) 28%, var(--aw-panel));
}
.col[data-state='live'] {
  border-color: var(--aw-info-line);
  background: color-mix(in srgb, var(--aw-info-soft) 35%, var(--aw-panel));
}

.col-head { display: flex; align-items: center; gap: .55rem; min-width: 0; }
.col-num {
  flex: none; display: grid; place-items: center;
  width: 1.5rem; height: 1.5rem; border-radius: 50%;
  background: var(--aw-panel); border: 1px solid var(--aw-border-strong);
  color: var(--aw-muted); font-family: var(--aw-font-mono); font-size: var(--aw-text-xs); font-weight: 700;
}
.col[data-state='done'] .col-num { border-color: var(--aw-ok); background: var(--aw-ok); color: var(--aw-on-accent); }
.col[data-state='current'] .col-num { border-color: var(--aw-teal); background: var(--aw-teal-soft); color: var(--aw-teal-strong); }
.col[data-state='live'] .col-num { border-color: var(--aw-info); background: var(--aw-info-soft); color: var(--aw-info); }

.col-copy { display: flex; flex-direction: column; gap: .1rem; min-width: 0; flex: 1; }
.col-copy h3 {
  margin: 0; color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.col[data-state='later'] .col-copy h3 { color: var(--aw-ink-soft); }
.col-sub { display: flex; align-items: center; gap: .4rem; font-size: var(--aw-text-xs); }
.col-status { color: var(--aw-muted); font-variant-numeric: tabular-nums; }
.col[data-state='done'] .col-status { color: var(--aw-ok); font-weight: 600; }
.col[data-state='current'] .col-status { color: var(--aw-teal-strong); font-weight: 600; }
.col[data-state='live'] .col-status { color: var(--aw-info); font-weight: 600; }
.col-gate {
  padding: 0 .4rem; border-radius: var(--aw-radius-pill);
  background: var(--aw-warn-soft); color: var(--aw-warn-ink);
  font-size: var(--aw-text-2xs); font-weight: 700;
}

.col-track { height: 4px; border-radius: 2px; background: var(--aw-border); overflow: hidden; }
.col-track i { display: block; height: 100%; border-radius: inherit; background: var(--aw-teal); }
.col[data-state='done'] .col-track i { background: var(--aw-ok); }
.col[data-state='live'] .col-track i { background: var(--aw-info); }

.cards { display: flex; flex-direction: column; gap: .5rem; min-width: 0; }

.card {
  display: flex; flex-direction: column; gap: .4rem; min-width: 0;
  padding: .65rem .75rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-control);
  background: var(--aw-panel);
  transition: border-color .12s ease;
}
.card:hover { border-color: var(--aw-border-strong); }
.card.ghost { background: color-mix(in srgb, var(--aw-panel) 70%, var(--aw-raised)); }
.card.lead { border-color: var(--aw-teal); background: var(--aw-panel); }
.card[data-live] { border-color: var(--aw-info-line); }

.card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: .5rem; }
.card-title {
  min-width: 0; color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-weight: 600;
  line-height: 1.3; text-decoration: none;
}
a.card-title:hover { color: var(--aw-teal-strong); text-decoration: underline; }
.card.ghost .card-title { color: var(--aw-ink-soft); }
.card.lead .card-title { color: var(--aw-teal-strong); }
.state-ico { flex: none; font-size: var(--aw-text-sm); margin-top: .1rem; }
.live-dot { flex: none; width: 9px; height: 9px; margin-top: .25rem; border-radius: 50%; background: var(--aw-info); }

.card-facts {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: .2rem .35rem;
  color: var(--aw-ink-soft); font-size: var(--aw-text-xs); line-height: 1.45;
}
.card-facts b { font-family: var(--aw-font-mono); font-weight: 600; color: var(--aw-ink); font-variant-numeric: tabular-nums; }
.card-facts b[data-severity='warning'] { color: var(--aw-warn-ink); }
.card-facts b[data-severity='error'] { color: var(--aw-danger-ink); }
.card.ghost .card-facts { color: var(--aw-muted); }
.sep { color: var(--aw-muted); }
.door { color: var(--aw-ink); text-decoration: underline; text-decoration-color: var(--aw-border-strong); text-underline-offset: 2px; }
.door:hover { color: var(--aw-teal-strong); text-decoration-color: currentColor; }

.card-warn {
  margin: 0; color: var(--aw-warn-ink); font-size: var(--aw-text-xs); line-height: 1.35;
}

.card-live {
  display: inline-flex; align-items: center; gap: .35rem; align-self: flex-start;
  padding: .15rem .45rem; border-radius: var(--aw-radius-pill);
  background: var(--aw-info-soft); color: var(--aw-info);
  font-size: var(--aw-text-xs); font-weight: 600;
}

.card-open {
  display: flex; flex-direction: column; gap: .2rem; width: 100%;
  padding: .4rem .55rem; border: 1px solid var(--aw-warn-line); border-radius: 6px;
  background: var(--aw-warn-soft); color: var(--aw-warn-ink);
  font: inherit; font-size: var(--aw-text-xs); text-align: left; cursor: pointer;
}
.card-open:hover { border-color: var(--aw-warn); background: var(--aw-panel); }
.open-msg { line-height: 1.35; }
.open-go { display: inline-flex; align-items: center; gap: .25rem; font-weight: 700; }
.open-go .aw-icon { font-size: var(--aw-text-2xs); }

.card-foot { display: flex; align-items: center; gap: .5rem; padding-top: .2rem; }
.grow { flex: 1; }
.tool-link {
  display: inline-flex; align-items: center; gap: .25rem;
  color: var(--aw-muted); font-size: var(--aw-text-xs); text-decoration: none;
}
.tool-link:hover { color: var(--aw-teal-strong); }
.text-act {
  padding: 0; border: 0; background: none; color: var(--aw-teal-strong);
  font: inherit; font-size: var(--aw-text-xs); font-weight: 600; cursor: pointer;
}
.text-act:hover { text-decoration: underline; }

@container (max-width: 62rem) {
  .board { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 34rem) {
  .board { grid-template-columns: minmax(0, 1fr); }
}
</style>
