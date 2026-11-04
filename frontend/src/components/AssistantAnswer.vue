<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { inlineParts } from '../services/assistant.js'
import { answerBlocks, presentAnswer } from '../services/answerFormatting.js'

const props = defineProps({ text: { type: String, default: '' }, sources: { type: Array, default: () => [] } })
const emit = defineEmits(['navigate'])
const answer = computed(() => presentAnswer(props.text, props.sources))
const blocks = computed(() => answerBlocks(props.text))
const sourcesExpanded = ref(false)
const visibleSources = computed(() => sourcesExpanded.value ? answer.value.sources : answer.value.sources.slice(0, 5))
function navigate(number) {
  const source = answer.value.sources.find(item => item.citation === number)
  if (source) emit('navigate', source)
}
</script>

<template>
  <div class="assistant-answer">
    <template v-for="(block, index) in blocks" :key="index">
      <pre v-if="block.type === 'code'" class="answer-code"><code>{{ block.text }}</code></pre>
      <component :is="block.type === 'heading' ? `h${block.level}` : 'p'" v-else class="answer-block">
        <template v-for="(part, partIndex) in inlineParts(block.text, sources)" :key="partIndex">
          <sup v-if="part.type === 'cite'" class="cite" role="button" tabindex="0" :aria-label="`查看引用 ${answer.citationNumbers.get(part.number)}`"
            @click="navigate(answer.citationNumbers.get(part.number))" @keydown.enter="navigate(answer.citationNumbers.get(part.number))"
            @keydown.space.prevent="navigate(answer.citationNumbers.get(part.number))">{{ answer.citationNumbers.get(part.number) }}</sup>
          <strong v-else-if="part.type === 'bold'">{{ part.text }}</strong>
          <code v-else-if="part.type === 'code'" class="inline-code">{{ part.text }}</code>
          <template v-else>{{ part.text }}</template>
        </template>
      </component>
    </template>
    <div v-if="answer.sources.length" class="assistant-card">
      <p class="assistant-card-title"><AppIcon name="quote" :size="12" />引用来源</p>
      <div v-for="source in visibleSources" :key="source.citation" class="source-item" role="button" tabindex="0"
        :title="`${source.paper_title}：${source.text}`" @click="navigate(source.citation)"
        @keydown.enter="navigate(source.citation)" @keydown.space.prevent="navigate(source.citation)">
        <span class="cite">{{ source.citation }}</span>
        <span class="source-page">第 {{ source.page }} 页</span>
        <span class="source-text">{{ source.text }}</span>
      </div>
      <button v-if="answer.sources.length > 5" type="button" class="sources-toggle" :aria-expanded="sourcesExpanded"
        @click="sourcesExpanded = !sourcesExpanded">{{ sourcesExpanded ? '收起' : `展开剩余 ${answer.sources.length - 5} 条引用` }}</button>
    </div>
  </div>
</template>

<style scoped>
.answer-block { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0 0 8px; }
p.answer-block { font-size: 13px; line-height: 1.7; }
h1.answer-block, h2.answer-block, h3.answer-block, h4.answer-block, h5.answer-block, h6.answer-block { line-height: 1.45; font-weight: 650; margin: 14px 0 8px; }
.answer-block:first-child { margin-top: 0; }
h1 { font-size: 20px; }
h2 { font-size: 18px; }
h3 { font-size: 16px; }
h4 { font-size: 14px; }
h5 { font-size: 13px; }
h6 { font-size: 12px; color: var(--text-2); }
.answer-code { white-space: pre-wrap; overflow-wrap: anywhere; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-s); background: var(--surface-2); font-size: 12px; line-height: 1.6; }
.inline-code { padding: 1px 4px; border-radius: 3px; background: var(--surface-2); font-size: .95em; }
.cite { display: inline-flex; align-items: center; justify-content: center; min-width: 15px; height: 15px; padding: 0 3px; margin: 0 2px; border-radius: 4px; background: var(--accent-soft); color: var(--accent); font-size: 10.5px; font-weight: 600; cursor: pointer; vertical-align: 2px; }
.source-item { display: flex; align-items: baseline; gap: 7px; font-size: 11.5px; line-height: 1.5; margin-top: 6px; cursor: pointer; }
.source-item:first-of-type { margin-top: 8px; }
.source-page { flex: none; color: var(--accent); font-weight: 550; }
.source-text { color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sources-toggle { display: block; margin: 8px 0 0; padding: 0; color: var(--accent); font-size: 11.5px; line-height: 1.5; cursor: pointer; }
</style>
