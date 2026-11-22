<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { FramePayload, VizSpec } from '../../types'
import FrameTable from '../FrameTable.vue'
import { layoutExhibit } from './exhibitCharts'

/**
 * One exhibit drawn as SVG from the layout `exhibitCharts` computes for its
 * width. Colours are the `--aw-chart-*` tokens, so the light and dark sheets
 * each get their own steps. A frame the spec cannot be drawn from is shown as
 * its table, and so is every exhibit before its width is known.
 */
const props = withDefaults(defineProps<{ frame: FramePayload; viz: VizSpec; tableHeight?: string }>(), {
  tableHeight: '260px',
})

const host = ref<HTMLElement>()
const width = ref(0)
let observer: ResizeObserver | null = null
onMounted(() => {
  if (!host.value) return
  width.value = host.value.clientWidth
  observer = new ResizeObserver(entries => { width.value = Math.floor(entries[0].contentRect.width) })
  observer.observe(host.value)
})
onBeforeUnmount(() => observer?.disconnect())

const layout = computed(() => width.value ? layoutExhibit(props.frame, props.viz, width.value) : null)

const tip = ref<{ lines: string[]; x: number; y: number } | null>(null)
function show(lines: string[] | undefined, event: MouseEvent | FocusEvent) {
  if (!lines?.length || !host.value) return
  const box = host.value.getBoundingClientRect()
  const target = (event.target as Element).getBoundingClientRect()
  const x = 'clientX' in event ? event.clientX : target.left + target.width / 2
  const y = 'clientY' in event ? event.clientY : target.top
  tip.value = { lines, x: Math.min(x - box.left + 14, box.width - 200), y: y - box.top + 14 }
}
</script>

<template>
  <div ref="host" class="exhibit-chart" @mouseleave="tip = null">
    <template v-if="layout">
      <ul v-if="layout.legend.length" class="exhibit-legend">
        <li v-for="item in layout.legend" :key="item.label">
          <i :class="[item.cls, { line: item.line }]" aria-hidden="true" />{{ item.label }}
        </li>
      </ul>
      <svg
        :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`"
        role="img" :aria-label="layout.aria" data-exhibit-chart
      >
        <template v-for="(mark, index) in layout.marks" :key="index">
          <line v-if="mark.kind === 'line'" :x1="mark.x1" :y1="mark.y1" :x2="mark.x2" :y2="mark.y2" :class="mark.cls" />
          <polyline v-else-if="mark.kind === 'polyline'" :points="mark.points" :class="mark.cls" />
          <path v-else-if="mark.kind === 'path'" :d="mark.d" :class="mark.cls" />
          <rect
            v-else-if="mark.kind === 'rect'" :x="mark.x" :y="mark.y" :width="mark.w" :height="mark.h" :rx="mark.rx ?? 0"
            :class="mark.cls" :tabindex="mark.tip ? 0 : undefined"
            @mousemove="show(mark.tip, $event)" @focus="show(mark.tip, $event)" @blur="tip = null"
          />
          <circle
            v-else-if="mark.kind === 'dot'" :cx="mark.cx" :cy="mark.cy" :r="mark.r" :class="mark.cls"
            :tabindex="mark.tip ? 0 : undefined"
            @mousemove="show(mark.tip, $event)" @focus="show(mark.tip, $event)" @blur="tip = null"
          />
          <text
            v-else-if="mark.kind === 'text'" :x="mark.x" :y="mark.y" :text-anchor="mark.anchor ?? 'start'" :class="mark.cls"
            :transform="mark.rotate ? `rotate(${mark.rotate} ${mark.x} ${mark.y})` : undefined"
          >{{ mark.text }}</text>
          <rect
            v-else-if="mark.kind === 'hit'" :x="mark.x" :y="mark.y" :width="mark.w" :height="mark.h" class="hit" tabindex="0"
            @mousemove="show(mark.tip, $event)" @focus="show(mark.tip, $event)" @blur="tip = null"
          />
        </template>
      </svg>
      <div v-if="tip" class="exhibit-tip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }" role="status">
        <b>{{ tip.lines[0] }}</b>
        <span v-for="(line, index) in tip.lines.slice(1)" :key="index">{{ line }}</span>
      </div>
    </template>
    <FrameTable v-else :frame="frame" :scrollHeight="tableHeight" />
  </div>
</template>

<style scoped>
.exhibit-chart { position: relative; width: 100%; padding: .75rem .875rem .5rem; box-sizing: border-box; }
svg { display: block; max-width: 100%; overflow: visible; font-family: var(--aw-font-sans); }

.grid { stroke: var(--aw-chart-grid); stroke-width: 1; }
.axis { stroke: var(--aw-chart-axis); stroke-width: 1; }
.reference { stroke: var(--aw-ink-soft); stroke-width: 1.5; }
.s1 { fill: var(--aw-chart-s1); }
.s2 { fill: var(--aw-chart-s2); }
.quiet { fill: var(--aw-chart-quiet); }
.critical { fill: var(--aw-chart-critical); }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.line.s1 { stroke: var(--aw-chart-s1); }
.line.s2 { stroke: var(--aw-chart-s2); }
.ring { stroke: var(--aw-sheet); stroke-width: 2; }
.whisker { stroke-width: 2; stroke-linecap: round; }
.whisker.quiet { stroke: var(--aw-chart-quiet); }
.whisker.critical { stroke: var(--aw-chart-critical); }
.box { fill: var(--aw-chart-s1-wash); stroke: var(--aw-chart-s1); stroke-width: 1; }
.breach { stroke: var(--aw-chart-critical); stroke-width: 2; }
.hit { fill: transparent; outline: none; }
.hit:focus-visible { stroke: var(--aw-teal); stroke-width: 1.5; }
.seq-1 { fill: var(--aw-chart-seq-1); } .seq-2 { fill: var(--aw-chart-seq-2); } .seq-3 { fill: var(--aw-chart-seq-3); }
.seq-4 { fill: var(--aw-chart-seq-4); } .seq-5 { fill: var(--aw-chart-seq-5); } .seq-6 { fill: var(--aw-chart-seq-6); }
.seq-ink-1 { fill: var(--aw-chart-seq-ink-1); } .seq-ink-2 { fill: var(--aw-chart-seq-ink-2); } .seq-ink-3 { fill: var(--aw-chart-seq-ink-3); }
.seq-ink-4 { fill: var(--aw-chart-seq-ink-4); } .seq-ink-5 { fill: var(--aw-chart-seq-ink-5); } .seq-ink-6 { fill: var(--aw-chart-seq-ink-6); }
.ord-1 { fill: var(--aw-chart-ord-1); } .ord-2 { fill: var(--aw-chart-ord-2); } .ord-3 { fill: var(--aw-chart-ord-3); }
.ord-4 { fill: var(--aw-chart-ord-4); } .ord-5 { fill: var(--aw-chart-ord-5); }
.ord-ink-1 { fill: var(--aw-chart-ord-ink-1); } .ord-ink-2 { fill: var(--aw-chart-ord-ink-2); } .ord-ink-3 { fill: var(--aw-chart-ord-ink-3); }
.ord-ink-4 { fill: var(--aw-chart-ord-ink-4); } .ord-ink-5 { fill: var(--aw-chart-ord-ink-5); }

text { font-size: 12px; fill: var(--aw-ink); }
.t-axis { font-size: 11px; fill: var(--aw-muted); font-variant-numeric: tabular-nums; }
.t-label { fill: var(--aw-ink); }
.t-head { font-size: 11px; fill: var(--aw-muted); }
.t-note { font-size: 11px; fill: var(--aw-ink-soft); }
.t-value { fill: var(--aw-ink-soft); font-variant-numeric: tabular-nums; }
.t-strong { fill: var(--aw-ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.t-crit { fill: var(--aw-danger); font-weight: 600; font-size: 11px; }
.t-in, .t-cell { font-size: 11px; font-weight: 500; font-variant-numeric: tabular-nums; }
.t-empty { fill: var(--aw-muted); }

.exhibit-legend {
  display: flex; flex-wrap: wrap; gap: .25rem 1rem; margin: 0 0 .5rem; padding: 0; list-style: none;
  font-family: var(--aw-font-sans); font-size: var(--aw-text-xs); color: var(--aw-ink-soft);
}
.exhibit-legend li { display: flex; align-items: center; gap: .375rem; }
.exhibit-legend i { width: 10px; height: 10px; border-radius: 2px; background: var(--aw-chart-s1); }
.exhibit-legend i.line { height: 3px; }
.exhibit-legend i.s2 { background: var(--aw-chart-s2); }
.exhibit-legend i.ord-1 { background: var(--aw-chart-ord-1); } .exhibit-legend i.ord-2 { background: var(--aw-chart-ord-2); }
.exhibit-legend i.ord-3 { background: var(--aw-chart-ord-3); } .exhibit-legend i.ord-4 { background: var(--aw-chart-ord-4); }
.exhibit-legend i.ord-5 { background: var(--aw-chart-ord-5); }

.exhibit-tip {
  position: absolute; z-index: 5; pointer-events: none; display: flex; flex-direction: column; gap: .125rem;
  max-width: 260px; padding: .4rem .55rem; border: 1px solid var(--aw-border-strong); border-radius: 6px;
  background: var(--aw-raised, var(--aw-sheet)); box-shadow: var(--aw-sheet-shadow);
  font-family: var(--aw-font-sans); font-size: var(--aw-text-xs); color: var(--aw-ink);
}
</style>
