<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
import SplitButton from 'primevue/splitbutton'
import type { MenuItem } from 'primevue/menuitem'

import { useWorkspaceNav } from '../../composables/useWorkspaceNavigation'
import { plural } from '../../format'
import type { EngagementOpenPoint, EngagementStage } from '../../types'
import UiStateIcon from '../ui/UiStateIcon.vue'
import type { RecordPhaseGroup, RecordStageItem, RecordStartRequest } from './recordViewModel'

const props = defineProps<{
  groups: RecordPhaseGroup[]
  openPoints: EngagementOpenPoint[]
  starting: string
}>()

const emit = defineEmits<{
  start: [stage: EngagementStage, alternate?: RecordStartRequest]
  'open-point': [point: EngagementOpenPoint]
}>()

const nav = useWorkspaceNav()

const allItems = computed(() => props.groups.flatMap(g => g.items))
const heldCount = computed(() => allItems.value.filter(i => i.stage.held).length)
const totalCount = computed(() => allItems.value.length)
const leadItem = computed(() => allItems.value.find(i => i.isLead) ?? null)

function startOptions(stage: EngagementStage): MenuItem[] {
  return (stage.start?.alternates ?? []).map(alternate => ({
    label: alternate.label,
    note: alternate.note,
    command: () => emit('start', stage, alternate),
  }))
}

function doorLinks(item: RecordStageItem) {
  return item.facts.filter(f => f.kind === 'door' && f.to)
}
</script>

<template>
  <section class="overview" aria-label="Engagement overview" data-testid="record-overview">
    <!-- Zone 1: Executive focus — next action on the left, human sign-offs on the right. -->
    <section class="focus">
      <div class="focus-pane">
        <div class="focus-head">
          <span class="focus-lbl">Progress</span>
          <strong class="focus-tally">{{ heldCount }} of {{ totalCount }} deliverables ready</strong>
        </div>

        <div class="phase-strip">
          <div v-for="group in groups" :key="group.id" class="mini" :data-state="group.live ? 'live' : group.state">
            <span class="mini-bar"><i :style="{ width: `${Math.round(group.fill * 100)}%` }" /></span>
            <span class="mini-lbl">{{ group.title }}</span>
          </div>
        </div>

        <div v-if="leadItem" class="next-box">
          <div class="next-copy">
            <span class="next-eyebrow">Next step</span>
            <strong>{{ leadItem.stage.filed?.label || leadItem.stage.capability }}</strong>
            <span v-if="leadItem.stage.headline" class="next-desc">{{ leadItem.stage.headline }}</span>
          </div>
          <Button
            v-if="leadItem.stage.action === 'import'"
            label="Import"
            size="small"
            @click="emit('start', leadItem.stage)"
          />
          <SplitButton
            v-else-if="leadItem.stage.start?.alternates.length"
            label="Run"
            size="small"
            :disabled="starting === leadItem.stage.capability"
            :model="startOptions(leadItem.stage)"
            @click="emit('start', leadItem.stage)"
          />
          <Button
            v-else
            label="Run"
            size="small"
            :loading="starting === leadItem.stage.capability"
            @click="emit('start', leadItem.stage)"
          />
        </div>
        <p v-else class="all-done">
          <i class="aw-icon aw-icon-circle-check" aria-hidden="true" />
          Every deliverable on the plan is in place.
        </p>
      </div>

      <div class="focus-pane gates" :data-open="openPoints.length ? '1' : null">
        <div class="focus-head">
          <span class="focus-lbl">Human sign-off</span>
          <span class="gate-badge" :data-tone="openPoints.length ? 'warn' : 'ok'">
            {{ openPoints.length ? plural(openPoints.length, 'open gate') : 'All signed off' }}
          </span>
        </div>

        <div v-if="openPoints.length" class="gate-list">
          <button
            v-for="point in openPoints"
            :key="point.key"
            type="button"
            class="gate-row"
            @click="emit('open-point', point)"
          >
            <span class="gate-msg">{{ point.message }}</span>
            <span class="gate-go">{{ point.action }} <i class="aw-icon aw-icon-arrow-right" aria-hidden="true" /></span>
          </button>
        </div>
        <p v-else class="gates-clear">
          <i class="aw-icon aw-icon-circle-check" aria-hidden="true" />
          No pending auditor review gates.
        </p>
      </div>
    </section>

    <!-- Zone 2: Quiet, uniform audit file launcher grouped softly by phase. -->
    <section class="file-groups" aria-label="Audit file deliverables">
      <div v-for="group in groups" :key="group.id" class="fgroup">
        <h3 class="fgroup-lbl">{{ group.index + 1 }} · {{ group.title }}</h3>
        <div class="fgrid">
          <div
            v-for="item in group.items"
            :key="item.stage.id"
            class="tile"
            :class="{ ghost: !item.stage.held, lead: item.isLead }"
          >
            <div class="tile-top">
              <component
                :is="item.destination ? RouterLink : 'span'"
                :to="item.destination ? nav.to(item.destination) : undefined"
                class="tile-name"
              >{{ item.stage.filed?.label || item.stage.capability }}</component>
              <UiStateIcon class="tile-state" :state="item.state" />
            </div>

            <p class="tile-stat">{{ item.primaryStat }}</p>

            <div v-if="doorLinks(item).length || item.stage.action === 'import'" class="tile-links">
              <template v-for="(door, idx) in doorLinks(item)" :key="door.text">
                <span v-if="idx" class="sep" aria-hidden="true">·</span>
                <RouterLink :to="nav.to(door.to!)" class="tile-link">
                  <b v-if="door.figure">{{ door.figure }}</b>{{ door.figure ? ' ' : '' }}{{ door.text }}
                </RouterLink>
              </template>
              <button
                v-if="item.stage.action === 'import'"
                type="button"
                class="tile-import"
                @click="emit('start', item.stage)"
              >{{ item.stage.held ? 'Import more' : 'Import' }}</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.overview { display: flex; flex-direction: column; gap: 1.125rem; }

.focus {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: .875rem;
}
.focus-pane {
  display: flex; flex-direction: column; gap: .75rem; min-width: 0;
  padding: 1rem 1.125rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-surface);
  background: var(--aw-panel);
}
.focus-pane.gates[data-open='1'] {
  border-color: var(--aw-warn-line);
  background: color-mix(in srgb, var(--aw-warn-soft) 45%, var(--aw-panel));
}

.focus-head { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.focus-lbl {
  color: var(--aw-muted); font-size: var(--aw-text-xs); font-weight: 700;
  text-transform: uppercase; letter-spacing: .04em;
}
.focus-tally { color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-variant-numeric: tabular-nums; }

.phase-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .5rem; }
.mini { display: flex; flex-direction: column; gap: .25rem; min-width: 0; }
.mini-bar { display: block; height: 5px; border-radius: 3px; background: var(--aw-border); overflow: hidden; }
.mini-bar i { display: block; height: 100%; border-radius: inherit; background: var(--aw-teal); }
.mini[data-state='done'] .mini-bar i { background: var(--aw-ok); }
.mini[data-state='live'] .mini-bar i { background: var(--aw-info); }
.mini-lbl {
  color: var(--aw-muted); font-size: var(--aw-text-2xs);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mini[data-state='current'] .mini-lbl { color: var(--aw-teal-strong); font-weight: 600; }

.next-box {
  display: flex; align-items: center; justify-content: space-between; gap: .75rem;
  padding: .65rem .8rem;
  border: 1px solid var(--aw-teal-line); border-radius: var(--aw-radius-control);
  background: color-mix(in srgb, var(--aw-teal-soft) 50%, var(--aw-panel));
}
.next-copy { display: flex; flex-direction: column; gap: .1rem; min-width: 0; }
.next-eyebrow { color: var(--aw-teal-strong); font-size: var(--aw-text-2xs); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.next-copy strong { color: var(--aw-ink-strong); font-size: var(--aw-text-sm); }
.next-desc { color: var(--aw-ink-soft); font-size: var(--aw-text-xs); }

.all-done, .gates-clear {
  margin: 0; display: flex; align-items: center; gap: .45rem;
  color: var(--aw-ok); font-size: var(--aw-text-sm); font-weight: 500;
}

.gate-badge {
  padding: .1rem .5rem; border-radius: var(--aw-radius-pill);
  font-size: var(--aw-text-xs); font-weight: 700;
}
.gate-badge[data-tone='warn'] { background: var(--aw-warn-soft); color: var(--aw-warn-ink); }
.gate-badge[data-tone='ok'] { background: var(--aw-ok-soft); color: var(--aw-ok); }

.gate-list { display: flex; flex-direction: column; gap: .4rem; }
.gate-row {
  display: flex; align-items: center; gap: .5rem; width: 100%;
  padding: .5rem .65rem;
  border: 1px solid var(--aw-warn-line); border-radius: var(--aw-radius-control);
  background: var(--aw-panel); color: var(--aw-warn-ink);
  font: inherit; font-size: var(--aw-text-xs); text-align: left; cursor: pointer;
}
.gate-row:hover { border-color: var(--aw-warn); background: var(--aw-warn-soft); }
.gate-msg { flex: 1; min-width: 0; line-height: 1.35; }
.gate-go { flex: none; display: inline-flex; align-items: center; gap: .25rem; font-weight: 700; }
.gate-go .aw-icon { font-size: var(--aw-text-2xs); }

.file-groups { display: flex; flex-direction: column; gap: .875rem; }
.fgroup { display: flex; flex-direction: column; gap: .45rem; }
.fgroup-lbl {
  margin: 0; color: var(--aw-muted); font-size: var(--aw-text-xs); font-weight: 700;
  text-transform: uppercase; letter-spacing: .04em;
}
.fgrid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .625rem;
}
.tile {
  display: flex; flex-direction: column; gap: .3rem; min-width: 0;
  padding: .7rem .85rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-control);
  background: var(--aw-panel);
  transition: border-color .12s ease;
}
.tile:hover { border-color: var(--aw-teal-line); }
.tile.ghost { background: color-mix(in srgb, var(--aw-raised) 50%, var(--aw-panel)); }
.tile.lead { border-color: var(--aw-teal); }

.tile-top { display: flex; align-items: center; justify-content: space-between; gap: .4rem; }
.tile-name {
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-weight: 600; text-decoration: none;
}
a.tile-name:hover { color: var(--aw-teal-strong); text-decoration: underline; }
.tile.ghost .tile-name { color: var(--aw-ink-soft); }
.tile-state { flex: none; font-size: var(--aw-text-sm); }

.tile-stat {
  margin: 0; color: var(--aw-ink-soft); font-size: var(--aw-text-xs);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.tile.ghost .tile-stat { color: var(--aw-muted); }

.tile-links { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem .35rem; font-size: var(--aw-text-xs); margin-top: .1rem; }
.tile-link { color: var(--aw-teal-strong); text-decoration: none; }
.tile-link:hover { text-decoration: underline; }
.tile-link b { font-family: var(--aw-font-mono); font-weight: 600; }
.sep { color: var(--aw-muted); }
.tile-import {
  margin-left: auto; padding: 0; border: 0; background: none;
  color: var(--aw-teal-strong); font: inherit; font-size: var(--aw-text-xs); font-weight: 600; cursor: pointer;
}
.tile-import:hover { text-decoration: underline; }

@container (max-width: 56rem) {
  .focus { grid-template-columns: minmax(0, 1fr); }
  .fgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 34rem) {
  .fgrid { grid-template-columns: minmax(0, 1fr); }
}
</style>
