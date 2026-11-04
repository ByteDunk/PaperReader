<script setup>
import { computed, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import IconButton from '../components/IconButton.vue'
import { initializeBookmarks, bookmarkIndex, bookmarksLoading, bookmarkSaving, openBookmarkEditor } from '../composables/useBookmarks.js'
import EmptyState from '../components/EmptyState.vue'
import RichText from '../components/RichText.vue'
import PdfAsset from '../components/PdfAsset.vue'
import { useReflowTracking } from '../composables/useReflowTracking'
import { readerSettings } from '../composables/useReaderSettings'
import { attachAssistantReference } from '../composables/useAssistantDrafts.js'
import { layout } from '../dock/useLayout'
import { activeId, activePaper, document as paperDocument, loading, error, locateSource } from '../composables/usePapers'

const scroll = ref(null)
const content = ref(null)
const activeToc = ref('')
function bookmarkFor(block) { return bookmarkIndex.value.get(`${activeId.value}/${block.id}`) }
const { onScroll, invalidateGeometry, goTo, cancelNavigation } = useReflowTracking(scroll, content, activeToc)
const view = ref(null)
const viewWidth = ref(0)
const resizingToc = ref(false)
const defaultTocWidth = computed(() => (viewWidth.value || 580) / 5)
const tocMinWidth = computed(() => Math.min(100, defaultTocWidth.value))
const tocMaxWidth = computed(() => Math.max(defaultTocWidth.value, Math.min(420, (viewWidth.value || 580) - 160)))
const tocWidth = computed(() => Number.isFinite(layout.reflowTocWidth)
  ? Math.max(tocMinWidth.value, Math.min(tocMaxWidth.value, layout.reflowTocWidth)) : defaultTocWidth.value)
let tocDrag = null
let sizeObserver

function setTocWidth(width) {
  layout.reflowTocWidth = Math.max(tocMinWidth.value, Math.min(tocMaxWidth.value, Math.round(width)))
}
function startTocResize(event) {
  if (event.button !== 0 || tocDrag) return
  event.preventDefault()
  tocDrag = { x: event.clientX, width: tocWidth.value, pointerId: event.pointerId, element: event.currentTarget }
  resizingToc.value = true
  event.currentTarget.setPointerCapture(event.pointerId)
}
function moveTocResize(event) {
  if (tocDrag && event.pointerId === tocDrag.pointerId) setTocWidth(tocDrag.width + event.clientX - tocDrag.x)
}
function stopTocResize() {
  const drag = tocDrag
  tocDrag = null
  resizingToc.value = false
  if (drag?.element.hasPointerCapture(drag.pointerId)) drag.element.releasePointerCapture(drag.pointerId)
}
function resizeTocByKey(event) {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
  event.preventDefault()
  setTocWidth(tocWidth.value + (event.key === 'ArrowRight' ? 16 : -16))
}
onMounted(() => {
  initializeBookmarks()
  viewWidth.value = view.value.clientWidth
  sizeObserver = new ResizeObserver(([entry]) => { viewWidth.value = entry.contentRect.width })
  sizeObserver.observe(view.value)
})
onDeactivated(stopTocResize)
onBeforeUnmount(() => { stopTocResize(); sizeObserver?.disconnect() })
const toc = computed(() => (paperDocument.value?.blocks || []).filter(b => b.type === 'heading').map(b => {
  const section = b.text.match(/^((?:\d+|[A-Z])(?:\.\d+)*)(?=\.?\s)/)
  return { id: b.id, label: b.text, depth: section ? section[1].split('.').length - 1 : 0 }
}))
const message = computed(() => !activePaper.value ? '请先导入论文' : activePaper.value.state === 'unparsed' ? '解析缓存已清理' : activePaper.value.state === 'failed' ? '重排失败' : '正在重排论文…')
</script>

<template>
  <div ref="view" class="reflow-view" :class="{ 'resizing-toc': resizingToc }">
    <aside class="toc-rail" :style="{ width: Number.isFinite(layout.reflowTocWidth) ? `${layout.reflowTocWidth}px` : '20%' }">
      <p class="toc-title">目录</p>
      <button v-for="t in toc" :key="t.id" class="toc-item" :class="{ active: t.id === activeToc }" :style="{ paddingInlineStart: `${8 + t.depth * 12}px` }" :title="t.label" @click="goTo(t.id)">{{ t.label }}</button>
    </aside>
    <div class="toc-divider" role="separator" aria-orientation="vertical"
      aria-label="调整目录宽度" :aria-valuenow="tocWidth" :aria-valuemin="tocMinWidth" :aria-valuemax="tocMaxWidth" tabindex="0"
      @pointerdown="startTocResize" @pointermove="moveTocResize" @pointerup="stopTocResize"
      @pointercancel="stopTocResize" @lostpointercapture="stopTocResize" @keydown="resizeTocByKey" />
    <div ref="scroll" class="reflow-scroll" @scroll.passive="onScroll" @load.capture="invalidateGeometry"
      @wheel.passive="cancelNavigation" @touchstart.passive="cancelNavigation" @pointerdown="cancelNavigation" @keydown="cancelNavigation">
      <EmptyState v-if="!paperDocument || loading" icon="article" :title="loading ? '正在加载重排内容…' : message" :hint="error || activePaper?.error || (activePaper?.state === 'unparsed' ? '在论文列表的更多操作中点击“重排论文”，重新生成阅读内容。' : '导入后会自动提取正文、图片与表格。')" />
      <article v-else ref="content" v-memo="[paperDocument, activeId, bookmarkIndex, bookmarksLoading, bookmarkSaving, readerSettings.titleFontSize, readerSettings.fontSize, readerSettings.lineHeight, readerSettings.showPageAnchors]" class="reflow-doc" :style="{ '--reader-title-font-size': `${readerSettings.titleFontSize}px`, '--reader-font-size': `${readerSettings.fontSize}px`, '--reader-line-height': readerSettings.lineHeight / 10 }">
        <p v-for="warning in paperDocument.warnings" :key="warning" class="doc-meta">{{ warning }}</p>
        <template v-for="(block, index) in paperDocument.blocks" :key="block.id">
          <div v-if="readerSettings.showPageAnchors && (index === 0 || block.page !== paperDocument.blocks[index - 1].page)" class="page-anchor"><span>第 {{ block.page }} 页</span></div>
          <div :id="block.id" class="block" :class="{ 'figure-block': block.asset && block.type !== 'equation', 'equation-block': block.type === 'equation' }" data-block :data-page="block.page" :data-heading="block.type === 'heading' ? '' : null">
            <h1 v-if="block.type === 'title'" class="doc-title">{{ block.text }}</h1>
            <h2 v-else-if="block.type === 'heading'" class="doc-h2">{{ block.text }}</h2>
            <template v-else-if="block.asset">
              <PdfAsset :paper-id="activeId" :block="block" :page="paperDocument.pages?.[block.page - 1]" />
              <p v-if="block.type !== 'equation' && block.caption"><RichText :text="block.caption" :spans="block.caption_spans" /></p>
            </template>
            <p v-else-if="block.type !== 'equation'" class="body-text"><RichText :text="block.text" :spans="block.spans" /></p>
            <div class="block-actions">
              <IconButton icon="crosshair" title="定位原文" aria-label="定位原文" @click="locateSource(block)" />
              <IconButton icon="bookmark" :active="Boolean(bookmarkFor(block))" :disabled="bookmarksLoading || bookmarkSaving"
                :title="bookmarkFor(block) ? '编辑书签备注' : '加入书签'" :aria-label="bookmarkFor(block) ? '编辑书签备注' : '加入书签'"
                :aria-pressed="Boolean(bookmarkFor(block))" @click="openBookmarkEditor(activeId, block, bookmarkFor(block))" />
              <IconButton icon="sparkles" title="询问 AI" aria-label="询问 AI" @click="attachAssistantReference(activeId, block)" />
            </div>
          </div>
        </template>
      </article>
    </div>
  </div>
</template>

<style scoped>
.reflow-view {
  position: relative;
  display: flex;
  height: 100%;
  min-height: 0;
}
.reflow-view.resizing-toc { user-select: none; cursor: col-resize; }
.toc-divider {
  position: relative;
  flex: none;
  width: 8px;
  margin-inline: -4px;
  z-index: 1;
  cursor: col-resize;
  touch-action: none;
}
.toc-divider::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 2px;
  background: transparent;
}
.toc-divider:hover::after,
.toc-divider:focus-visible::after,
.resizing-toc .toc-divider::after { background: var(--accent); }
.toc-rail {
  flex: none;
  min-width: min(100px, 20%);
  max-width: max(20%, min(420px, calc(100% - 160px)));
  border-right: 1px solid var(--border);
  padding: 12px 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.toc-title {
  flex-shrink: 0;
  margin: 0 0 6px;
  padding: 0 8px;
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.5px;
}
.toc-item {
  flex-shrink: 0;
  text-align: left;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
  padding: 5px 8px;
  border-radius: var(--radius-s);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.toc-item:hover {
  background: var(--surface-2);
  color: var(--text);
}
.toc-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.reflow-scroll {
  contain: layout paint style;
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  /* KeepAlive restoration owns the position; browser anchoring otherwise
     applies another adjustment when the detached document is laid out again. */
  overflow-anchor: none;
}
.reflow-doc {
  max-width: 660px;
  margin: 0 auto;
  padding: 30px 36px 72px;
  font-family: var(--font-serif);
}
.page-anchor {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 22px 0 18px;
  color: var(--text-3);
  font-family: var(--font-ui);
  font-size: 11px;
}
.page-anchor::before,
.page-anchor::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.block {
  /* Keep offscreen text out of resize layout while retaining its measured height. */
  content-visibility: auto;
  contain-intrinsic-size: auto 100px;
  min-height: var(--control-height);
  overflow-wrap: anywhere;
  position: relative;
  border-radius: var(--radius-s);
}
.block:hover {
  background: var(--surface-2);
}
.doc-title {
  margin: 4px 0 6px;
  font-size: var(--reader-title-font-size, 20px);
  font-weight: 650;
  line-height: 1.4;
}
.doc-meta {
  margin: 0 0 14px;
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--text-3);
}
.doc-h2 {
  margin: 18px 0 8px;
  font-size: var(--reader-title-font-size, 20px);
  font-weight: 650;
}
.block p {
  margin: 0 0 10px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--text);
  text-align: justify;
}
.block .body-text {
  font-size: var(--reader-font-size, 14px);
  line-height: var(--reader-line-height, 1.8);
}
.block-actions {
  position: absolute;
  bottom: 0;
  right: 0;
  display: flex;
  gap: 2px;
  z-index: 1;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.block:hover .block-actions, .block:focus-within .block-actions {
  opacity: 1;
}
.figure-block {
  margin: 16px 0;
  padding: 2px 0;
}
.equation-block {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 16px 0;
}
@media (hover: none) { .block-actions { opacity: 1; } }
</style>
