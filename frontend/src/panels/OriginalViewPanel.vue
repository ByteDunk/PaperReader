<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import IconButton from '../components/IconButton.vue'
import EmptyState from '../components/EmptyState.vue'
import PdfImage from '../components/PdfImage.vue'
import { apiUrl } from '../services/desktop.js'
import { layout, panelColumn } from '../dock/useLayout.js'
import { activeId, activePaper as selectedPaper, document as paperDocument, reading, sourceTarget, updateReading, locateReflow } from '../composables/usePapers'

// App keys this instance by paper ID. Its images and pending callbacks must
// remain attached to that paper even while the next reader is being mounted.
const paperId = activeId.value
const activePaper = computed(() => selectedPaper.value?.id === paperId ? selectedPaper.value : null)
let restoreVersion = 0
let readerActive = false
let restoring = false
let locatedTarget = null
let sizeObserver
let viewWidth = 0
const scroll = ref(null)
const dragging = ref(false)
let drag = null
const zoom = ref(100)
const minZoom = 25
const maxZoom = 400
const currentPage = ref(1)
const pageDraft = ref('')
const pageFocused = ref(false)
const continuous = ref(true)
const failedPages = ref(new Set())
const pageNumbers = computed(() => activePaper.value ? Array.from({ length: activePaper.value.pages }, (_, i) => i + 1).filter(n => continuous.value || n === currentPage.value) : [])
async function showPosition(position, target = null) {
  if (!readerActive || activeId.value !== paperId || !activePaper.value) return
  const version = ++restoreVersion
  restoring = true
  currentPage.value = Math.min(activePaper.value.pages, Math.max(1, position.page || 1))
  await nextTick()
  if (!readerActive || activeId.value !== paperId || version !== restoreVersion) return
  const transitions = scroll.value?.closest('.dock-column')?.getAnimations()
    .filter(animation => animation.transitionProperty === 'width') || []
  await Promise.allSettled(transitions.map(animation => animation.finished))
  if (!readerActive || activeId.value !== paperId || version !== restoreVersion) return
  const el = scroll.value
  const page = el?.querySelector(`[data-page="${currentPage.value}"]`)
  if (page && el.clientHeight) {
    const bounds = page.getBoundingClientRect()
    const viewport = el.getBoundingClientRect()
    const pageTop = bounds.top - viewport.top - el.clientTop + el.scrollTop
    const pageLeft = bounds.left - viewport.left - el.clientLeft + el.scrollLeft
    const offset = Number.isFinite(position.originalPageOffset) ? position.originalPageOffset : 0
    const sourcePage = target && paperDocument.value?.pages[currentPage.value - 1]
    const x = sourcePage ? (target.bbox[0] + target.bbox[2]) / (2 * sourcePage.width) : (position.originalCenter ?? .5)
    const top = sourcePage ? pageTop + (target.bbox[1] + target.bbox[3]) / (2 * sourcePage.height) * bounds.height - el.clientHeight / 2
      : pageTop + offset * bounds.height
    const left = pageLeft + x * bounds.width - el.clientWidth / 2
    el.scrollTo({ top, left, behavior: 'instant' })
    if (target) locatedTarget = target
  }
  restoring = false
  trackScroll()
}
function goPage(number) {
  trackScroll()
  return showPosition({ page: number, originalPageOffset: 0, originalCenter: reading[paperId]?.originalCenter ?? .5 })
}
function toggleContinuous() {
  trackScroll()
  continuous.value = !continuous.value
  showPosition({ ...reading[paperId] })
}
function inputPage(event) {
  pageDraft.value = event.target.value
  const page = Number(pageDraft.value)
  if (/^\d+$/.test(pageDraft.value) && page >= 1 && page <= activePaper.value?.pages) goPage(page)
}
function restore() {
  if (!readerActive || activeId.value !== paperId) return
  failedPages.value = new Set()
  const target = sourceTarget.value
  // A source jump is consumed once; later tab switches resume the saved offset.
  const pendingTarget = target?.paperId === paperId && target !== locatedTarget
  return showPosition(pendingTarget ? { page: target.page, originalPageOffset: 0 } : { ...reading[paperId] }, pendingTarget ? target : null)
}
watch([sourceTarget, paperDocument], restore)
watch(zoom, async () => {
  const el = scroll.value
  if (!readerActive || activeId.value !== paperId || !el?.clientHeight) return
  const center = viewCenter(el)
  const pages = [...el.querySelectorAll('[data-page]')]
  const page = pages.find(page => page.getBoundingClientRect().bottom > center.y) || pages.at(-1)
  if (!page) return
  // Keep the same page coordinates under the viewport center after resizing.
  const before = page.getBoundingClientRect()
  const x = (center.x - before.left) / before.width
  const y = (center.y - before.top) / before.height
  const version = ++restoreVersion
  restoring = true
  await nextTick()
  if (!readerActive || activeId.value !== paperId || version !== restoreVersion) return
  const after = page.getBoundingClientRect()
  const nextCenter = viewCenter(el)
  el.scrollBy({ left: after.left + x * after.width - nextCenter.x,
    top: after.top + y * after.height - nextCenter.y, behavior: 'instant' })
  restoring = false
  trackScroll()
})
function viewCenter(el) {
  const bounds = el.getBoundingClientRect()
  return { x: bounds.left + el.clientLeft + el.clientWidth / 2,
    y: bounds.top + el.clientTop + el.clientHeight / 2 }
}
function startDrag(event) {
  if (event.button !== 0 || event.pointerType !== 'mouse' || !activePaper.value || event.target.closest('button, a, input')) return
  const el = scroll.value
  event.preventDefault()
  cancelRestore()
  drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop }
  dragging.value = true
  el.setPointerCapture(event.pointerId)
}
function moveDrag(event) {
  if (!drag || event.pointerId !== drag.pointerId) return
  scroll.value.scrollTo({ left: drag.left + drag.x - event.clientX,
    top: drag.top + drag.y - event.clientY, behavior: 'instant' })
}
function stopDrag() {
  if (!drag) return
  const { pointerId } = drag
  drag = null
  dragging.value = false
  if (scroll.value?.hasPointerCapture(pointerId)) scroll.value.releasePointerCapture(pointerId)
  trackScroll()
}
function cancelRestore(event) {
  if (event?.type === 'keydown' && !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) return
  ++restoreVersion
  restoring = false
  if (sourceTarget.value?.paperId === paperId) locatedTarget = sourceTarget.value
}
onMounted(() => {
  sizeObserver = new ResizeObserver(() => {
    const width = scroll.value?.clientWidth
    if (!width) return
    const changed = viewWidth && viewWidth !== width
    viewWidth = width
    if (changed && readerActive && !restoring && !drag) showPosition({ ...reading[paperId] })
  })
  sizeObserver.observe(scroll.value)
})
onActivated(() => { readerActive = true; restore() })
function deactivate() { stopDrag(); readerActive = false; restoring = false; pageFocused.value = false; ++restoreVersion }
onDeactivated(deactivate)
onBeforeUnmount(() => { deactivate(); sizeObserver?.disconnect() })
// KeepAlive detaches the DOM before onDeactivated, so capture even a scroll
// whose event has not fired yet while the reader still has its visible layout.
watch(() => {
  const column = layout.columns[panelColumn('original')]
  return column?.active === 'original' && !column.collapsed
}, visible => {
  if (!visible) trackScroll()
}, { flush: 'sync' })
function pageUrl(number) { return apiUrl(`/api/papers/${paperId}/pages/${number}.png`, true) }
function onPageLoad(event) {
  // Before parsing completes, the PDF may have a different shape than the
  // portrait placeholder. Reapply the saved anchor after its real size arrives.
  if (!paperDocument.value && !drag && event.target.src.startsWith('blob:')) showPosition({ ...reading[paperId] })
}
function trackScroll() {
  const el = scroll.value
  if (!readerActive || restoring || activeId.value !== paperId || !el?.clientHeight) return
  const top = el.getBoundingClientRect().top + el.clientTop
  const visible = [...el.querySelectorAll('[data-page]')].find(page => page.getBoundingClientRect().bottom > top + 15)
  if (visible) {
    const bounds = visible.getBoundingClientRect()
    // A page-relative offset survives changes to the reader column's width.
    currentPage.value = Number(visible.dataset.page)
    updateReading({ page: currentPage.value, originalPageOffset: (top - bounds.top) / bounds.height,
      originalCenter: (viewCenter(el).x - bounds.left) / bounds.width })
  }
}
function highlight(number) {
  const target = sourceTarget.value
  const page = paperDocument.value?.pages[number - 1]
  if (!target || target.paperId !== activeId.value || target.page !== number || !page) return null
  const [x0, y0, x1, y1] = target.bbox
  return { left: `${x0 / page.width * 100}%`, top: `${y0 / page.height * 100}%`, width: `${(x1 - x0) / page.width * 100}%`, height: `${(y1 - y0) / page.height * 100}%` }
}
</script>

<template>
  <div class="original-view">
    <div class="viewer-toolbar">
      <IconButton icon="zoom-out" title="缩小" :disabled="!activePaper || zoom <= minZoom" @click="zoom = Math.max(minZoom, zoom - 25)" />
      <input v-model.number="zoom" class="zoom-slider" type="range" :min="minZoom" :max="maxZoom" step="5"
        :disabled="!activePaper" aria-label="PDF 缩放倍率" :aria-valuetext="`${zoom}%`" :title="`缩放 ${zoom}%`" />
      <span class="zoom-num">{{ zoom }}%</span>
      <IconButton icon="zoom-in" title="放大" :disabled="!activePaper || zoom >= maxZoom" @click="zoom = Math.min(maxZoom, zoom + 25)" />
      <IconButton icon="maximize" title="恢复默认倍率" @click="zoom = 100" />
      <span class="t-divider" />
      <IconButton icon="chevron-left" title="上一页" :disabled="!activePaper || currentPage <= 1" @click="goPage(currentPage - 1)" />
      <span class="page-ind">
        <label class="ui-field" :style="{ width: `${Math.max(2, String(activePaper?.pages || 0).length) + 3.6}ch` }">
          <input type="text" inputmode="numeric" aria-label="当前页码" :disabled="!activePaper"
            :value="pageFocused ? pageDraft : activePaper ? currentPage : 0"
            @focus="pageFocused = true; pageDraft = $event.target.value; $event.target.select()" @click="$event.target.select()"
            @input="inputPage" @blur="pageFocused = false" @keydown.enter="$event.target.blur()" />
        </label><span class="page-total">/ {{ activePaper?.pages || 0 }}</span>
      </span>
      <IconButton icon="chevron-right" title="下一页" :disabled="!activePaper || currentPage >= activePaper.pages" @click="goPage(currentPage + 1)" />
      <span class="t-divider" />
      <IconButton icon="rows" title="连续滚动" :active="continuous" @click="toggleContinuous" />
    </div>
    <div ref="scroll" class="page-scroll" :class="{ pannable: activePaper, dragging }" @scroll.passive="trackScroll"
      @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="stopDrag" @pointercancel="stopDrag"
      @lostpointercapture="stopDrag" @dragstart.prevent @wheel.passive="cancelRestore" @touchstart.passive="cancelRestore" @keydown="cancelRestore">
      <EmptyState v-if="!activePaper" icon="file-text" title="请先导入论文" hint="导入 PDF 后即可阅读原文。" />
      <div v-for="number in pageNumbers" :key="`${paperId}-${number}`" class="page-item"
        :style="{ width: `${zoom * .92}%`, maxWidth: `${600 * zoom / 100}px` }">
        <div class="pdf-page" :data-page="number">
          <PdfImage v-if="!failedPages.has(number)" :src="pageUrl(number)" :alt="`第 ${number} 页原文`"
            :source-width="paperDocument?.pages[number - 1]?.width || 0"
            :width="paperDocument?.pages[number - 1]?.width || 595" :height="paperDocument?.pages[number - 1]?.height || 842"
            style="display: block; width: 100%; height: auto;" @load="onPageLoad" @error="failedPages.add(number)" />
          <EmptyState v-else class="page-error" icon="file-text" title="页面加载失败" hint="请检查后端连接后重新打开论文。"
            :style="{ aspectRatio: (paperDocument?.pages[number - 1]?.width || 595) / (paperDocument?.pages[number - 1]?.height || 842) }" />
          <div v-if="highlight(number)" class="bbox-highlight" :style="highlight(number)">
            <div class="bbox-actions">
              <span class="bbox-tag">已定位原文</span>
              <button type="button" class="bbox-reflow" title="前往论文文本相应位置" aria-label="前往论文文本相应位置" @click="locateReflow()">
                <AppIcon name="arrow-right" :size="14" />
              </button>
            </div>
          </div>
        </div>
        <p class="page-no">第 {{ number }} 页</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.original-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.viewer-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  flex: none;
}
.zoom-slider {
  flex: 1 1 90px;
  max-width: 160px;
  accent-color: var(--accent);
}
.zoom-num {
  min-width: 44px;
  text-align: center;
  font-size: 12px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.t-divider {
  width: 1px;
  height: 18px;
  background: var(--border);
  margin: 0 5px;
}
.page-ind {
  --control-padding: 5px;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: var(--text-2);
  min-width: 46px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.page-ind input { text-align: right; }
.page-total { transform: translateY(1px); }
.page-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-anchor: none;
  background: var(--surface-2);
  padding: 22px 16px 30px;
}
.page-scroll.pannable { cursor: grab; user-select: none; }
.page-scroll.dragging { cursor: grabbing; }
.page-item { margin: 0 auto; }
.pdf-page {
  position: relative;
  margin: 0 0 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: var(--shadow-sm);
}
.page-error { justify-content: center; }
.bbox-highlight {
  position: absolute;
  border: 1.5px solid var(--accent);
  border-radius: 5px;
  background: var(--accent-soft);
}
.bbox-actions {
  position: absolute;
  bottom: calc(100% + 6px);
  left: -1.5px;
  z-index: 1;
  display: flex;
  gap: 4px;
  width: max-content;
  height: 22px;
}
.bbox-tag,
.bbox-reflow {
  --accent: var(--button-accent);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  border-radius: 5px;
  background: var(--accent);
  color: var(--on-accent);
}
.bbox-tag {
  padding: 2px 8px;
  font-size: 11px;
  white-space: nowrap;
}
.bbox-reflow {
  width: 22px;
  height: 22px;
  transition: background-color .15s ease;
}
.bbox-reflow:hover {
  background: var(--button-accent-hover);
}
.page-no {
  text-align: center;
  font-size: 11.5px;
  color: var(--text-3);
  margin: 2px 0 0;
}
</style>
