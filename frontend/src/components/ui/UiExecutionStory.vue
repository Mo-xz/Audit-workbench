<script setup lang="ts">
import { computed } from 'vue'

/**
 * Three-step visual architecture strip shared by Analysis and Data Tests:
 *
 *   1. Authored Logic   — AI (purple) or auditor designed the rule/test
 *   2. Local Execution  — Polars ran deterministically on 100% of rows (0 raw rows sent to LLM)
 *   3. Human Governance — auditor review, exception ruling, or sign-off state
 *
 * Purely presentational: every number and status arrives from the parent surface.
 */

export type ExecutionStoryTone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral'

const props = defineProps<{
  /** Step 1: who authored the logic and what engine runs it. */
  aiAuthored: boolean
  authorBadge?: string
  engineLabel: string
  ruleTitle: string
  scopeLabel?: string

  /** Step 2: deterministic local execution over the population. */
  ran: boolean
  population?: number | null
  tested?: number | null
  exceptions?: number | null
  /** True when returned rows represent exceptions/breaches rather than informational aggregates. */
  tracksExceptions?: boolean
  verdictText?: string | null
  executionError?: string | null

  /** Step 3: human-in-the-loop governance state. */
  humanTitle: string
  humanDetail: string
  humanTone: ExecutionStoryTone
  humanBadge?: string
}>()

const popTotal = computed(() => {
  const value = props.population ?? props.tested ?? null
  return typeof value === 'number' && value > 0 ? value : null
})

const exceptionCount = computed(() => Math.max(0, props.exceptions ?? 0))

const compliantCount = computed(() => {
  if (!popTotal.value) return null
  return Math.max(0, popTotal.value - exceptionCount.value)
})

const exceptionPercent = computed(() => {
  if (!popTotal.value || !exceptionCount.value) return 0
  // Keep even a tiny non-zero exception slice visible on the bar.
  return Math.max(3, Math.min(100, Math.round((exceptionCount.value / popTotal.value) * 100)))
})

const compliantPercent = computed(() => {
  if (!popTotal.value) return 0
  return Math.max(0, 100 - exceptionPercent.value)
})

const rateLabel = computed(() => {
  if (!popTotal.value || !exceptionCount.value) return ''
  const pct = (exceptionCount.value / popTotal.value) * 100
  return pct < 0.1 ? '<0.1%' : `${Math.round(pct * 10) / 10}%`
})

const coverageLabel = computed(() => {
  if (!props.ran) return 'Not yet executed'
  if (props.executionError) return 'Execution error'
  if (popTotal.value && props.tested && props.tested < popTotal.value) {
    return `${props.tested.toLocaleString()} of ${popTotal.value.toLocaleString()} comparable`
  }
  if (popTotal.value) return `100% of ${popTotal.value.toLocaleString()} rows scanned`
  return 'Executed locally on full table'
})
</script>

<template>
  <section class="story-strip" aria-label="How this check was designed, run, and governed">
    <!-- Step 1: AI / Auditor Logic -->
    <article class="step-card" :class="{ ai: aiAuthored }">
      <header class="step-head">
        <span class="step-num">1</span>
        <span class="step-pill" :data-kind="aiAuthored ? 'ai' : 'human'">
          <i class="aw-icon" :class="aiAuthored ? 'aw-icon-sparkles' : 'aw-icon-user-pen'" aria-hidden="true" />
          {{ authorBadge || (aiAuthored ? 'AI authored' : 'Auditor authored') }}
        </span>
        <span class="step-engine">{{ engineLabel }}</span>
      </header>
      <strong class="step-title">{{ ruleTitle }}</strong>
      <p v-if="scopeLabel" class="step-detail">
        <i class="aw-icon aw-icon-database" aria-hidden="true" />
        <span>{{ scopeLabel }}</span>
      </p>
    </article>

    <!-- Step 2: Deterministic Local Polars Execution -->
    <article class="step-card local">
      <header class="step-head">
        <span class="step-num">2</span>
        <span class="step-pill" data-kind="local">
          <i class="aw-icon aw-icon-shield" aria-hidden="true" />
          Local Polars
        </span>
        <span class="privacy-tag">
          <i class="aw-icon aw-icon-lock" aria-hidden="true" />0 rows sent to AI
        </span>
      </header>

      <template v-if="!ran">
        <strong class="step-title muted">Ready to run locally</strong>
        <p class="step-detail">Runs deterministically on your machine over the full table.</p>
      </template>
      <template v-else-if="executionError">
        <strong class="step-title bad">Execution failed</strong>
        <p class="step-detail">{{ executionError }}</p>
      </template>
      <template v-else>
        <div class="pop-headline">
          <strong v-if="tracksExceptions && exceptionCount > 0" class="step-title bad aw-figure">
            {{ exceptionCount.toLocaleString() }}
            <template v-if="popTotal">of {{ popTotal.toLocaleString() }}</template>
            flagged
          </strong>
          <strong v-else-if="tracksExceptions" class="step-title ok aw-figure">
            0 exceptions
            <template v-if="popTotal">in {{ popTotal.toLocaleString() }} rows</template>
          </strong>
          <strong v-else class="step-title aw-figure">
            {{ verdictText || coverageLabel }}
          </strong>
          <span v-if="tracksExceptions && rateLabel" class="rate-chip aw-figure">{{ rateLabel }}</span>
        </div>

        <div v-if="popTotal && tracksExceptions" class="pop-bar-wrap">
          <div class="pop-bar" role="img" :aria-label="`${compliantCount ?? 0} compliant, ${exceptionCount} flagged`">
            <span class="bar-ok" :style="{ width: `${compliantPercent}%` }" />
            <span v-if="exceptionCount > 0" class="bar-exc" :style="{ width: `${exceptionPercent}%` }" />
          </div>
          <span class="step-meta">{{ coverageLabel }}</span>
        </div>
        <p v-else class="step-detail">{{ coverageLabel }}</p>
      </template>
    </article>

    <!-- Step 3: Human in the Loop -->
    <article class="step-card" :data-tone="humanTone">
      <header class="step-head">
        <span class="step-num">3</span>
        <span class="step-pill" :data-kind="humanTone === 'ok' ? 'ok' : 'warn'">
          <i class="aw-icon" :class="humanTone === 'ok' ? 'aw-icon-circle-check' : 'aw-icon-user-pen'" aria-hidden="true" />
          {{ humanBadge || 'Human in the loop' }}
        </span>
      </header>
      <strong class="step-title">{{ humanTitle }}</strong>
      <p class="step-detail">{{ humanDetail }}</p>
    </article>
  </section>
</template>

<style scoped>
.story-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14.5rem, 1fr));
  gap: .625rem;
  flex: none;
  min-width: 0;
}

.step-card {
  display: flex;
  flex-direction: column;
  gap: .35rem;
  min-width: 0;
  padding: .65rem .75rem;
  border: 1px solid var(--aw-border);
  border-radius: var(--aw-radius-control);
  background: var(--aw-panel);
}
.step-card.ai {
  border-color: var(--aw-accent-line);
  background: color-mix(in srgb, var(--aw-accent-soft) 55%, var(--aw-panel));
}
.step-card.local {
  border-color: var(--aw-teal-line);
  background: color-mix(in srgb, var(--aw-teal-soft) 50%, var(--aw-panel));
}
.step-card[data-tone='warn'] {
  border-color: var(--aw-warn-line);
  background: color-mix(in srgb, var(--aw-warn-soft) 55%, var(--aw-panel));
}
.step-card[data-tone='bad'] {
  border-color: var(--aw-danger-line);
  background: color-mix(in srgb, var(--aw-danger-soft) 45%, var(--aw-panel));
}
.step-card[data-tone='ok'] {
  border-color: var(--aw-ok-line);
  background: color-mix(in srgb, var(--aw-ok-soft) 50%, var(--aw-panel));
}

.step-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .35rem;
}
.step-num {
  display: grid;
  place-items: center;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 50%;
  background: var(--aw-raised);
  color: var(--aw-muted);
  font-size: var(--aw-text-2xs);
  font-weight: 800;
  flex: none;
}
.step-pill {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .06rem .45rem;
  border-radius: var(--aw-radius-pill);
  font-size: var(--aw-text-2xs);
  font-weight: 700;
  white-space: nowrap;
}
.step-pill[data-kind='ai'] { background: var(--aw-accent-soft); color: var(--aw-accent); border: 1px solid var(--aw-accent-line); }
.step-pill[data-kind='local'] { background: var(--aw-teal-soft); color: var(--aw-teal-strong); border: 1px solid var(--aw-teal-line); }
.step-pill[data-kind='warn'] { background: var(--aw-warn-soft); color: var(--aw-warn-ink); border: 1px solid var(--aw-warn-line); }
.step-pill[data-kind='ok'] { background: var(--aw-ok-soft); color: var(--aw-ok); border: 1px solid var(--aw-ok-line); }
.step-pill[data-kind='human'] { background: var(--aw-raised); color: var(--aw-ink-soft); border: 1px solid var(--aw-border); }

.step-engine {
  margin-left: auto;
  color: var(--aw-muted);
  font-size: var(--aw-text-2xs);
  font-weight: 600;
}
.privacy-tag {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: .2rem;
  color: var(--aw-teal-strong);
  font-size: var(--aw-text-2xs);
  font-weight: 600;
  white-space: nowrap;
}
.privacy-tag .aw-icon { font-size: var(--aw-text-2xs); }

.step-title {
  color: var(--aw-ink-strong);
  font-size: var(--aw-text-sm);
  font-weight: 700;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.step-title.ok { color: var(--aw-ok); }
.step-title.bad { color: var(--aw-danger); }
.step-title.muted { color: var(--aw-muted); font-weight: 600; }

.step-detail {
  display: flex;
  align-items: flex-start;
  gap: .3rem;
  margin: 0;
  color: var(--aw-ink-soft);
  font-size: var(--aw-text-xs);
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.step-detail .aw-icon { margin-top: .15rem; color: var(--aw-muted); font-size: var(--aw-text-2xs); flex: none; }

.pop-headline {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: .4rem;
}
.rate-chip {
  padding: .05rem .38rem;
  border-radius: var(--aw-radius-pill);
  background: var(--aw-danger-soft);
  color: var(--aw-danger);
  font-size: var(--aw-text-2xs);
  font-weight: 700;
  flex: none;
}
.pop-bar-wrap { display: flex; flex-direction: column; gap: .25rem; }
.pop-bar {
  display: flex;
  height: .4rem;
  width: 100%;
  border-radius: var(--aw-radius-pill);
  background: var(--aw-raised);
  overflow: hidden;
}
.bar-ok { background: var(--aw-teal-600); height: 100%; }
.bar-exc { background: var(--aw-danger); height: 100%; }
.step-meta { color: var(--aw-muted); font-size: var(--aw-text-2xs); font-weight: 500; }
</style>
