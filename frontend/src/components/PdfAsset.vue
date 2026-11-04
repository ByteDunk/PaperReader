<script setup>
import { computed } from 'vue'
import PdfImage from './PdfImage.vue'
import { apiUrl } from '../services/desktop.js'

const props = defineProps({
  paperId: { type: String, required: true },
  block: { type: Object, required: true },
  page: { type: Object, default: undefined },
  inline: { type: Boolean, default: false },
})
const src = computed(() => apiUrl(`/api/papers/${props.paperId}/assets/${props.block.asset}`, true))
const size = computed(() => {
  const box = props.block.bbox
  if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) return {}
  const [x0, y0, x1, y1] = box
  if (x1 <= x0 || y1 <= y0) return {}
  // Match the two-point crop padding, including clipping at the page edges.
  const width = Math.min(props.page?.width ?? Infinity, x1 + 2) - Math.max(0, x0 - 2)
  const height = Math.min(props.page?.height ?? Infinity, y1 + 2) - Math.max(0, y0 - 2)
  return width > 0 && height > 0 ? { width, height } : {}
})
const width = computed(() => {
  const value = props.block.display_width
  if (props.inline) return value > 0 ? `${value / 11}em` : 'auto'
  if (props.block.type === 'equation') return value > 0 ? `${value}px` : 'auto'
  return '100%'
})
const alt = computed(() => props.inline || props.block.type === 'equation'
  ? props.block.text || '论文公式'
  : props.block.caption || (props.block.type === 'table' ? '论文表格' : '论文插图'))
</script>

<template>
  <PdfImage class="pdf-asset" :class="{ 'inline-equation': inline }" :src="src" :alt="alt"
    :source-width="size.width || block.display_width || 0" v-bind="size" :style="{ width }" />
</template>

<style scoped>
.pdf-asset { display: block; max-width: 100%; height: auto; }
.inline-equation { display: inline-block; vertical-align: middle; }
</style>
