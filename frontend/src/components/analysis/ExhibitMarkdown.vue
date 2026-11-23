<script setup lang="ts">
import { computed } from 'vue'

import type { SavedAnalysis } from '../../types'
import MarkdownView from '../MarkdownView.vue'
import type { DocumentOptions } from '../ui/markdownHtml'
import ExhibitFigure from './ExhibitFigure.vue'
import { memoSegments } from './memoExhibits'

/**
 * A Markdown body that carries analysis exhibits: its prose as the document
 * draws prose, and each `embed` block as the exhibit it names, numbered from
 * `firstNumber` so a document drawn in pieces numbers them as one.
 */
const props = defineProps<{
  markdown: string
  workspaceId: string
  analyses: SavedAnalysis[]
  firstNumber: number
  document?: DocumentOptions
}>()
const emit = defineEmits<{ open: [analysisId: string] }>()

const byId = computed(() => Object.fromEntries(props.analyses.map(item => [item.id, item])))
const parts = computed(() => {
  let number = props.firstNumber - 1
  return memoSegments(props.markdown).map(segment =>
    segment.kind === 'embed' ? { ...segment, number: ++number } : { ...segment, number: 0 })
})
</script>

<template>
  <template v-for="(part, index) in parts" :key="index">
    <MarkdownView v-if="part.kind === 'prose'" :markdown="part.text" :document="document" />
    <ExhibitFigure
      v-else
      :workspaceId="workspaceId"
      :embed="part.embed"
      :number="part.number"
      :analysis="byId[part.embed.analysis]"
      @open="emit('open', $event)"
    />
  </template>
</template>
