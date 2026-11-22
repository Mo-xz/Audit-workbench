<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  starting: string
}>()

const emit = defineEmits<{
  start: [stage: EngagementStage, alternate?: RecordStartRequest]
  'open-point': [point: EngagementOpenPoint]
}>()

const nav = useWorkspaceNav()

const defaultId = computed(() =>
  props.groups.find(g => g.live)?.id
  ?? props.groups.find(g => g.state === 'current')?.id
  ?? props.groups.find(g => g.openPoints > 0)?.id
  ?? props.groups[0]?.id
  ?? '',
)
const activeId = ref(defaultId.value)
watch(() => props.groups.map(g => g.id).join(','), () => {
  if (!props.groups.some(g => g.id === activeId.value)) activeId.value = defaultId.value
}, { immediate: true })

const activeGroup = computed(() => props.groups.find(g => g.id === activeId.value) ?? props.groups[0] ?? null)
const activeIndex = computed(() => props.groups.findIndex(g => g.id === activeGroup.value?.id))

function step(delta: number) {
  const next = props.groups[activeIndex.value + delta]
  if (next) activeId.value = next.id
}

function startOptions(stage: EngagementStage): MenuItem[] {
  return (stage.start?.alternates ?? []).map(alternate => ({
    label: alternate.label,
    note: alternate.note,
    command: () => emit('start', stage, alternate),
  }))
}

function doorFacts(item: RecordStageItem) {
  return item.facts.filter(f => f.kind === 'door' || f.kind === 'tool')
}
function summaryFacts(item: RecordStageItem) {
  return item.facts.filter(f => f.kind !== 'door' && f.kind !== 'tool' && f.kind !== 'owed')
}
</script>

<template>
  <section class="phases-view" aria-label="Audit phases" data-testid="record-phases">
    <div class="tabs" role="tablist" aria-label="Engagement phases">
      <button
        v-for="group in groups"
        :key="group.id"
        type="button"
        role="tab"
        class="tab"
        :aria-selected="group.id === activeGroup?.id"
        :data-state="group.live ? 'live' : group.state"
        @click="activeId = group.id"
      >
        <span class="tab-num" aria-hidden="true">{{ group.index + 1 }}</span>
        <span class="tab-copy">
          <span class="tab-title">{{ group.title }}</span>
          <span class="tab-meta">
            <span class="tab-status">{{ group.statusLabel }}</span>
            <span v-if="group.openPoints" class="tab-gate">{{ plural(group.openPoints, 'review') }}</span>
          </span>
        </span>
      </button>
    </div>

    <section v-if="activeGroup" class="stage-panel" role="tabpanel">
      <header class="panel-head">
        <div class="panel-copy">
          <h3>{{ activeGroup.index + 1 }}. {{ activeGroup.title }}</h3>
          <span class="panel-sub">{{ activeGroup.headline }} · {{ activeGroup.held }} of {{ activeGroup.total }} deliverables ready</span>
        </div>
        <div class="stepper">
          <Button
            icon="aw-icon aw-icon-chevron-left"
            size="small"
            severity="secondary"
            outlined
            aria-label="Previous phase"
            :disabled="activeIndex <= 0"
            @click="step(-1)"
          />
          <Button
            icon="aw-icon aw-icon-chevron-right"
            size="small"
            severity="secondary"
            outlined
            aria-label="Next phase"
            :disabled="activeIndex >= groups.length - 1"
            @click="step(1)"
          />
        </div>
      </header>

      <div class="stage-cards">
        <article
          v-for="item in activeGroup.items"
          :key="item.stage.id"
          class="scard"
          :class="{ ghost: !item.stage.held, lead: item.isLead }"
          :data-live="item.live || null"
        >
          <div class="scard-main">
            <span v-if="item.live" class="live-dot" aria-hidden="true" />
            <UiStateIcon v-else class="state-ico" :state="item.state" />

            <div class="scard-copy">
              <div class="scard-top">
                <span class="step-code">{{ item.stepLabel }}</span>
                <component
                  :is="item.destination ? RouterLink : 'span'"
                  :to="item.destination ? nav.to(item.destination) : undefined"
                  class="scard-title"
                >{{ item.stage.filed?.label || item.stage.capability }}</component>
              </div>

              <div v-if="summaryFacts(item).length || item.attentionReason" class="scard-line">
                <template v-for="(fact, idx) in summaryFacts(item)" :key="`${fact.kind}:${idx}`">
                  <span v-if="idx" class="sep" aria-hidden="true">·</span>
                  <span :class="fact.kind">
                    <b v-if="fact.figure">{{ fact.figure }}</b>{{ fact.figure ? ' ' : '' }}{{ fact.text }}<template
                      v-for="(part, at) in fact.parts ?? []"
                      :key="part.text"
                    >{{ at ? ', ' : fact.text ? ' ' : '' }}<b :data-severity="part.severity || null">{{ part.figure }}</b> {{ part.text }}</template>
                  </span>
                </template>
                <span v-if="item.attentionReason" class="warn-txt">
                  <template v-if="summaryFacts(item).length"> · </template>{{ item.attentionReason }}
                </span>
              </div>

              <div v-if="doorFacts(item).length" class="door-pills">
                <template v-for="door in doorFacts(item)" :key="`${door.kind}:${door.text}`">
                  <RouterLink
                    v-if="door.to"
                    :to="nav.to(door.to)"
                    class="door-pill"
                    :data-kind="door.kind"
                  >
                    <i v-if="door.kind === 'tool'" class="aw-icon aw-icon-wrench" aria-hidden="true" />
                    <b v-if="door.figure">{{ door.figure }}</b>
                    <span>{{ door.text }}</span>
                    <i class="aw-icon aw-icon-arrow-right" aria-hidden="true" />
                  </RouterLink>
                </template>
              </div>
            </div>

            <div class="scard-act">
              <Button
                v-if="item.stage.action === 'import' && item.isLead"
                label="Import"
                size="small"
                @click="emit('start', item.stage)"
              />
              <Button
                v-else-if="item.stage.action === 'import'"
                :label="item.stage.held ? 'Import more' : 'Import'"
                size="small"
                severity="secondary"
                outlined
                @click="emit('start', item.stage)"
              />
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
              <RouterLink
                v-else-if="item.stage.held && item.destination"
                :to="nav.to(item.destination)"
                class="open-link"
              >Open <i class="aw-icon aw-icon-arrow-right" aria-hidden="true" /></RouterLink>
            </div>
          </div>

          <div v-if="item.live" class="scard-live">
            <i :class="item.live === 'running' ? 'aw-icon aw-icon-spin aw-icon-loader-circle' : 'aw-icon aw-icon-clock'" aria-hidden="true" />
            <span>
              {{ item.live === 'running' ? (item.stage.held ? 'Running again' : 'The assistant is working on it now.') : 'Scheduled by the run in progress.' }}
              <template v-if="item.liveElapsed"> · {{ item.liveElapsed }}</template>
              <template v-if="item.liveActivity"> · {{ item.liveActivity }}</template>
            </span>
          </div>

          <button
            v-for="point in item.stage.open_points"
            :key="point.key"
            type="button"
            class="scard-open"
            @click="emit('open-point', point)"
          >
            <i class="aw-icon aw-icon-triangle-alert" aria-hidden="true" />
            <span class="open-msg">{{ point.message }}</span>
            <span class="open-go">{{ point.action }} <i class="aw-icon aw-icon-arrow-right" aria-hidden="true" /></span>
          </button>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.phases-view { display: flex; flex-direction: column; gap: 1rem; }

.tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .5rem;
}
.tab {
  display: flex; align-items: center; gap: .625rem; min-width: 0;
  padding: .75rem .875rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-surface);
  background: color-mix(in srgb, var(--aw-raised) 50%, var(--aw-panel));
  font: inherit; text-align: left; cursor: pointer;
  transition: border-color .14s ease, background-color .14s ease;
}
.tab:hover { border-color: var(--aw-border-strong); background: var(--aw-panel); }
.tab[aria-selected='true'] {
  border-color: var(--aw-teal);
  background: var(--aw-panel);
  box-shadow: inset 0 -2px 0 var(--aw-teal);
}
.tab:focus-visible { outline: 2px solid var(--aw-teal); outline-offset: 2px; }

.tab-num {
  flex: none; display: grid; place-items: center;
  width: 1.65rem; height: 1.65rem; border-radius: 50%;
  border: 1px solid var(--aw-border-strong); background: var(--aw-panel);
  color: var(--aw-muted); font-family: var(--aw-font-mono); font-size: var(--aw-text-xs); font-weight: 700;
}
.tab[data-state='done'] .tab-num { border-color: var(--aw-ok); background: var(--aw-ok); color: var(--aw-on-accent); }
.tab[data-state='current'] .tab-num { border-color: var(--aw-teal); background: var(--aw-teal-soft); color: var(--aw-teal-strong); }
.tab[data-state='live'] .tab-num { border-color: var(--aw-info); background: var(--aw-info-soft); color: var(--aw-info); }

.tab-copy { display: flex; flex-direction: column; gap: .15rem; min-width: 0; flex: 1; }
.tab-title {
  color: var(--aw-ink-strong); font-size: var(--aw-text-sm); font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tab[data-state='later'] .tab-title { color: var(--aw-ink-soft); }
.tab-meta { display: flex; align-items: center; gap: .4rem; font-size: var(--aw-text-xs); }
.tab-status { color: var(--aw-muted); font-variant-numeric: tabular-nums; }
.tab[data-state='done'] .tab-status { color: var(--aw-ok); font-weight: 600; }
.tab[data-state='current'] .tab-status { color: var(--aw-teal-strong); font-weight: 600; }
.tab[data-state='live'] .tab-status { color: var(--aw-info); font-weight: 600; }
.tab-gate {
  padding: 0 .4rem; border-radius: var(--aw-radius-pill);
  background: var(--aw-warn-soft); color: var(--aw-warn-ink);
  font-size: var(--aw-text-2xs); font-weight: 700;
}

.stage-panel {
  display: flex; flex-direction: column; gap: .875rem;
  padding: 1.125rem 1.25rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-surface);
  background: var(--aw-panel);
}
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.panel-copy { display: flex; flex-direction: column; gap: .15rem; min-width: 0; }
.panel-copy h3 { margin: 0; color: var(--aw-ink-strong); font-size: var(--aw-text-md); font-weight: 700; }
.panel-sub { color: var(--aw-muted); font-size: var(--aw-text-sm); font-variant-numeric: tabular-nums; }
.stepper { display: flex; gap: .35rem; }

.stage-cards { display: flex; flex-direction: column; gap: .625rem; }

.scard {
  display: flex; flex-direction: column; gap: .625rem;
  padding: .875rem 1rem;
  border: 1px solid var(--aw-border); border-radius: var(--aw-radius-control);
  background: var(--aw-panel);
  transition: border-color .12s ease;
}
.scard:hover { border-color: var(--aw-border-strong); }
.scard.ghost { background: color-mix(in srgb, var(--aw-raised) 45%, var(--aw-panel)); }
.scard.lead { border-color: var(--aw-teal); background: color-mix(in srgb, var(--aw-teal-soft) 35%, var(--aw-panel)); }

.scard-main { display: flex; align-items: flex-start; gap: .75rem; min-width: 0; }
.state-ico { flex: none; margin-top: .2rem; font-size: var(--aw-text-base); }
.live-dot { flex: none; width: 10px; height: 10px; margin-top: .35rem; border-radius: 50%; background: var(--aw-info); }

.scard-copy { display: flex; flex-direction: column; gap: .35rem; flex: 1; min-width: 0; }
.scard-top { display: flex; align-items: baseline; gap: .5rem; min-width: 0; }
.step-code { color: var(--aw-muted); font-family: var(--aw-font-mono); font-size: var(--aw-text-xs); }
.scard-title { color: var(--aw-ink-strong); font-size: var(--aw-text-md); font-weight: 600; text-decoration: none; }
a.scard-title:hover { color: var(--aw-teal-strong); text-decoration: underline; }
.scard.ghost .scard-title { color: var(--aw-ink-soft); }

.scard-line { color: var(--aw-ink-soft); font-size: var(--aw-text-sm); line-height: 1.45; }
.scard-line b { font-family: var(--aw-font-mono); font-weight: 600; color: var(--aw-ink); font-variant-numeric: tabular-nums; }
.scard-line b[data-severity='warning'] { color: var(--aw-warn-ink); }
.scard-line b[data-severity='error'] { color: var(--aw-danger-ink); }
.sep { margin: 0 .35rem; color: var(--aw-muted); }
.warn-txt { color: var(--aw-warn-ink); }

.door-pills { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .15rem; }
.door-pill {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .25rem .6rem; border: 1px solid var(--aw-border); border-radius: var(--aw-radius-pill);
  background: var(--aw-raised); color: var(--aw-ink); font-size: var(--aw-text-xs); text-decoration: none;
}
.door-pill:hover { border-color: var(--aw-teal-line); background: var(--aw-teal-soft); color: var(--aw-teal-strong); }
.door-pill b { font-family: var(--aw-font-mono); font-weight: 700; }
.door-pill .aw-icon { font-size: var(--aw-text-2xs); color: var(--aw-muted); }

.scard-act { flex: none; display: flex; align-items: center; }
.open-link {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .3rem .65rem; border: 1px solid var(--aw-border); border-radius: var(--aw-radius-control);
  color: var(--aw-ink); font-size: var(--aw-text-sm); font-weight: 500; text-decoration: none;
}
.open-link:hover { border-color: var(--aw-teal-line); background: var(--aw-teal-soft); color: var(--aw-teal-strong); }
.open-link .aw-icon { font-size: var(--aw-text-xs); }

.scard-live {
  display: inline-flex; align-items: center; gap: .4rem; align-self: flex-start;
  padding: .25rem .6rem; border-radius: var(--aw-radius-pill);
  background: var(--aw-info-soft); color: var(--aw-info);
  font-size: var(--aw-text-xs); font-weight: 600;
}

.scard-open {
  display: flex; align-items: center; gap: .5rem; width: 100%;
  padding: .45rem .65rem; border: 1px solid var(--aw-warn-line); border-radius: var(--aw-radius-control);
  background: var(--aw-warn-soft); color: var(--aw-warn-ink);
  font: inherit; font-size: var(--aw-text-sm); text-align: left; cursor: pointer;
}
.scard-open:hover { border-color: var(--aw-warn); background: var(--aw-panel); }
.open-msg { flex: 1; min-width: 0; }
.open-go { display: inline-flex; align-items: center; gap: .25rem; flex: none; font-weight: 700; }
.open-go .aw-icon { font-size: var(--aw-text-xs); }

@container (max-width: 52rem) {
  .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
