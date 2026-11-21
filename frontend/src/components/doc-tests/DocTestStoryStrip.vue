<script setup lang="ts">
import { computed } from 'vue'

/**
 * Three-step visual architecture strip for Document Tests (Cycle Vouching,
 * Population Q&A, and Cited Q&A) — the document-evidence counterpart to
 * `UiExecutionStory.vue`:
 *
 *   1. Authored Rule    — AI (purple) or auditor defined the assertions / question
 *   2. Evidence Reading — AI vouched extracted fields across documents with page citations
 *   3. Human Governance — auditor calls on items/records and control sign-off
 */

export type DocStoryTone = 'ok' | 'warn' | 'bad' | 'neutral'

const props = defineProps<{
  aiAuthored: boolean
  engineLabel: string
  ruleTitle: string
  scopeLabel?: string

  ran: boolean
  passedCount: number
  failedCount: number
  reviewCount?: number
  totalCount: number
  unitLabel: string
  evidenceBadge?: string
  coverageMeta?: string

  humanTitle: string
  humanDetail: string
  humanTone: DocStoryTone
  humanBadge?: string
}>()

const total = computed(() => Math.max(0, props.totalCount))
const passed = computed(() => Math.max(0, props.passedCount))
const failed = computed(() => Math.max(0, props.failedCount))
const review = computed(() => Math.max(0, props.reviewCount ?? 0))

const passedPct = computed(() => (total.value ? Math.round((passed.value / total.value) * 100) : 0))
const failedPct = computed(() => {
  if (!total.value || !failed.value) return 0
  return Math.max(4, Math.round((failed.value / total.value) * 100))
})
const reviewPct = computed(() => {
  if (!total.value || !review.value) return 0
  return Math.max(4, Math.min(100 - failedPct.value, Math.round((review.value / total.value) * 100)))
})
const adjustedPassedPct = computed(() => {
  if (!total.value || !passed.value) return 0
  return Math.max(0, Math.min(100 - failedPct.value - reviewPct.value, passedPct.value))
})
</script>

<template>
  <section class="story-strip" aria-label="How this document test was designed, vouched, and governed">
    <!-- Step 1: Rule / Test Design -->
    <article class="step-card" :class="{ ai: aiAuthored }">
      <header class="step-head">
        <span class="step-num">1</span>
        <span class="step-pill" :data-kind="aiAuthored ? 'ai' : 'human'">
          <i class="aw-icon" :class="aiAuthored ? 'aw-icon-sparkles' : 'aw-icon-user-pen'" aria-hidden="true" />
          {{ aiAuthored ? 'AI authored' : 'Auditor authored' }}
        </span>
        <span class="step-engine">{{ engineLabel }}</span>
      </header>
      <strong class="step-title">{{ ruleTitle }}</strong>
      <p v-if="scopeLabel" class="step-detail">
        <i class="aw-icon aw-icon-book-open" aria-hidden="true" />
        <span>{{ scopeLabel }}</span>
      </p>
    </article>

    <!-- Step 2: AI Evidence Verification -->
    <article class="step-card evidence">
      <header class="step-head">
        <span class="step-num">2</span>
        <span class="step-pill" data-kind="evidence">
          <i class="aw-icon aw-icon-file-check" aria-hidden="true" />
          Evidence reading
        </span>
        <span v-if="evidenceBadge" class="cite-tag">
          {{ evidenceBadge }}
        </span>
      </header>

      <template v-if="!ran">
        <strong class="step-title muted">Not yet executed</strong>
        <p class="step-detail">Run this test to verify extracted document evidence with page citations.</p>
      </template>
      <template v-else>
        <div class="headline-row">
          <strong v-if="failed > 0" class="step-title bad aw-figure">
            {{ failed.toLocaleString() }} of {{ total.toLocaleString() }} {{ unitLabel }} flagged
          </strong>
          <strong v-else-if="review > 0" class="step-title warn aw-figure">
            {{ passed.toLocaleString() }} verified · {{ review.toLocaleString() }} to review
          </strong>
          <strong v-else-if="total > 0" class="step-title ok aw-figure">
            {{ passed.toLocaleString() }} of {{ total.toLocaleString() }} {{ unitLabel }} verified
          </strong>
          <strong v-else class="step-title muted">0 {{ unitLabel }} evaluated</strong>
        </div>

        <div v-if="total > 0" class="bar-wrap">
          <div
            class="bar"
            role="img"
            :aria-label="`${passed} verified, ${review} needing review, ${failed} flagged out of ${total} ${unitLabel}`"
          >
            <span v-if="adjustedPassedPct > 0" class="seg-ok" :style="{ width: `${adjustedPassedPct}%` }" />
            <span v-if="reviewPct > 0" class="seg-warn" :style="{ width: `${reviewPct}%` }" />
            <span v-if="failedPct > 0" class="seg-bad" :style="{ width: `${failedPct}%` }" />
          </div>
          <span v-if="coverageMeta" class="step-meta">{{ coverageMeta }}</span>
        </div>
        <p v-else-if="coverageMeta" class="step-detail">{{ coverageMeta }}</p>
      </template>
    </article>

    <!-- Step 3: Human Governance -->
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
.step-card.evidence {
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
.step-pill[data-kind='evidence'] { background: var(--aw-teal-soft); color: var(--aw-teal-strong); border: 1px solid var(--aw-teal-line); }
.step-pill[data-kind='warn'] { background: var(--aw-warn-soft); color: var(--aw-warn-ink); border: 1px solid var(--aw-warn-line); }
.step-pill[data-kind='ok'] { background: var(--aw-ok-soft); color: var(--aw-ok); border: 1px solid var(--aw-ok-line); }
.step-pill[data-kind='human'] { background: var(--aw-raised); color: var(--aw-ink-soft); border: 1px solid var(--aw-border); }

.step-engine {
  margin-left: auto;
  color: var(--aw-muted);
  font-size: var(--aw-text-2xs);
  font-weight: 600;
}
.cite-tag {
  margin-left: auto;
  color: var(--aw-teal-strong);
  font-size: var(--aw-text-2xs);
  font-weight: 600;
  white-space: nowrap;
}

.step-title {
  color: var(--aw-ink-strong);
  font-size: var(--aw-text-sm);
  font-weight: 700;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.step-title.ok { color: var(--aw-ok); }
.step-title.warn { color: var(--aw-warn-ink); }
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

.headline-row { display: flex; align-items: baseline; justify-content: space-between; gap: .4rem; }
.bar-wrap { display: flex; flex-direction: column; gap: .25rem; }
.bar {
  display: flex;
  height: .4rem;
  width: 100%;
  border-radius: var(--aw-radius-pill);
  background: var(--aw-raised);
  overflow: hidden;
}
.seg-ok { background: var(--aw-teal-600); height: 100%; }
.seg-warn { background: var(--aw-warn); height: 100%; }
.seg-bad { background: var(--aw-danger); height: 100%; }
.step-meta { color: var(--aw-muted); font-size: var(--aw-text-2xs); font-weight: 500; }
</style>
