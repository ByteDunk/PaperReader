<script setup>
import { computed, onBeforeUnmount } from 'vue'
import { layout, resizingColumn } from './useLayout'

const props = defineProps({ column: { type: String, required: true } })
const state = computed(() => layout.columns[props.column])
let drag = null

function setWidth(width, element) {
  const area = element.parentElement
  const style = getComputedStyle(area)
  const available = area.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
  const other = layout.columns[props.column === 'left' ? 'right' : 'left']
  const dividers = [...area.querySelectorAll(':scope > .resize-divider')].reduce((sum, el) => sum + el.offsetWidth, 0)
  const maximum = Math.max(180, Math.min(620, available - (other.collapsed ? 44 : other.width) - dividers - 280))
  state.value.width = Math.round(Math.max(180, Math.min(maximum, width)))
}

function start(event) {
  if (event.button !== 0 || state.value.collapsed) return
  event.preventDefault()
  drag = { x: event.clientX, width: state.value.width, pointerId: event.pointerId }
  resizingColumn.value = props.column
  event.currentTarget.setPointerCapture(event.pointerId)
}

function move(event) {
  if (!drag || resizingColumn.value !== props.column) return
  setWidth(drag.width + (event.clientX - drag.x) * (props.column === 'left' ? 1 : -1), event.currentTarget)
}

function stop(event) {
  if (drag && event?.currentTarget?.hasPointerCapture(drag.pointerId)) event.currentTarget.releasePointerCapture(drag.pointerId)
  drag = null
  if (resizingColumn.value === props.column) resizingColumn.value = ''
}

function keyboard(event) {
  if (state.value.collapsed || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return
  event.preventDefault()
  const direction = (event.key === 'ArrowRight' ? 1 : -1) * (props.column === 'left' ? 1 : -1)
  setWidth(state.value.width + direction * 16, event.currentTarget)
}
onBeforeUnmount(stop)
</script>

<template>
  <div class="resize-divider" :class="{ disabled: state.collapsed, resizing: resizingColumn === column }"
    role="separator" aria-orientation="vertical" :aria-label="column === 'left' ? '调整左边栏宽度' : '调整右边栏宽度'"
    :aria-valuenow="state.width" :aria-valuemin="180" :aria-valuemax="620" :aria-disabled="state.collapsed"
    :tabindex="state.collapsed ? -1 : 0" @pointerdown="start" @pointermove="move" @pointerup="stop"
    @pointercancel="stop" @lostpointercapture="stop" @keydown="keyboard" />
</template>

<style scoped>
.resize-divider {
  width: var(--dock-gap);
  flex: none;
  position: relative;
  cursor: col-resize;
  touch-action: none;
}
.resize-divider::after {
  content: '';
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  border-radius: 2px;
  background: transparent;
}
.resize-divider:hover::after,
.resize-divider:focus-visible::after,
.resize-divider.resizing::after { background: var(--accent); }
.resize-divider.disabled { cursor: default; }
.resize-divider.disabled::after { background: transparent; }
</style>
