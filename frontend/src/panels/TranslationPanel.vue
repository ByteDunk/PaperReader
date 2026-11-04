<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import SegmentedControl from '../components/SegmentedControl.vue'
import IconButton from '../components/IconButton.vue'
import AppIcon from '../components/AppIcon.vue'
import AppBadge from '../components/AppBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import RichText from '../components/RichText.vue'
import PdfAsset from '../components/PdfAsset.vue'
import { activeId, activePaper, document as paperDocument, paperActions, retranslatePaper, error as paperError } from '../composables/usePapers'
import { readerSettings } from '../composables/useReaderSettings'
import { translation, translationError, translationLoading, translationPage, translationPageProgress, translationForeground, initializeTranslations, refreshTranslation, disposeTranslations } from '../composables/useTranslations.js'

const mode = ref('both')
const modeOptions = [
  { value: 'both', label: '对照' },
  { value: 'dst', label: '仅译文' },
]

const body = ref(null)
const content = ref(null)
const actionError = ref('')
const copied = ref('')
let copyTimer
let scrollFrame = null
let sizeObserver
let foreground = true
let scrollRange = null
const blocks = computed(() => translation.value?.paperId === activeId.value
  ? translation.value.blocks : [])
const displayedPage = computed(() => translation.value?.paperId === activeId.value ? translation.value.page : translationPage.value)
const canRetry = computed(() => activePaper.value?.state === 'ready' && !paperActions[activeId.value])
const message = computed(() => !activePaper.value ? '请先导入论文' : translationLoading.value ? '正在加载译文…'
  : activePaper.value.state === 'unparsed' ? '解析与译文缓存已清理，请先重排论文'
  : activePaper.value.state === 'parsing' ? '正在提取本页内容…' : '本页暂无可翻译内容')

initializeTranslations()
function syncScroll() {
  scrollFrame = null
  const el = body.value
  if (!foreground || !translationForeground.value || !el || !blocks.value.length
    || displayedPage.value !== translationPage.value) return
  if (scrollRange === null) scrollRange = Math.max(0, el.scrollHeight - el.clientHeight)
  const target = translationPageProgress.value * scrollRange
  if (Math.abs(el.scrollTop - target) > .5) el.scrollTop = target
}
function scheduleScroll() {
  // Follow every frame within the displayed page; a deferred page switch must
  // not apply the next page's progress to the translation still on screen.
  if (foreground && translationForeground.value && displayedPage.value === translationPage.value
    && scrollFrame === null) scrollFrame = requestAnimationFrame(syncScroll)
}
function invalidateScrollRange() {
  scrollRange = null
  scheduleScroll()
}
onMounted(() => {
  sizeObserver = new ResizeObserver(invalidateScrollRange)
  sizeObserver.observe(body.value)
  sizeObserver.observe(content.value)
  scheduleScroll()
})
onActivated(() => { foreground = true; invalidateScrollRange() })
onDeactivated(() => { foreground = false; cancelAnimationFrame(scrollFrame); scrollFrame = null })
onBeforeUnmount(() => {
  disposeTranslations()
  clearTimeout(copyTimer)
  cancelAnimationFrame(scrollFrame)
  sizeObserver?.disconnect()
})
watch([activeId, displayedPage], () => {
  actionError.value = copied.value = ''
})
watch([activeId, translationPage, translationPageProgress, translationForeground,
  displayedPage, mode], scheduleScroll, { flush: 'post' })
watch([translation, mode, () => readerSettings.titleFontSize, () => readerSettings.fontSize, () => readerSettings.lineHeight], invalidateScrollRange, { flush: 'post' })
async function retry(blockId = null) {
  const id = activeId.value
  actionError.value = ''
  const ok = await retranslatePaper(id, blockId, blockId === null)
  if (id !== activeId.value) return
  if (!ok) actionError.value = paperError.value
  await refreshTranslation()
}
async function copy(block) {
  const id = activeId.value
  try {
    await navigator.clipboard.writeText(block.original_only ? block.src : block.dst || block.text || '')
    if (id !== activeId.value) return
    copied.value = block.id
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = '' }, 1600)
  } catch { if (id === activeId.value) actionError.value = '无法复制，请检查浏览器剪贴板权限。' }
}
</script>

<template>
  <div class="translation-view" :style="{ '--reader-title-font-size': `${readerSettings.titleFontSize}px`, '--reader-font-size': `${readerSettings.fontSize}px`, '--reader-line-height': readerSettings.lineHeight / 10 }">
    <div class="trans-head">
      <AppBadge tone="blue">第 {{ displayedPage }} 页</AppBadge>
      <span class="block-count">{{ blocks.length }} 个块</span>
      <span class="spacer" />
      <SegmentedControl v-model="mode" :options="modeOptions" />
    </div>

    <div ref="body" class="trans-body">
      <div ref="content" class="trans-content">
      <div v-if="translationError || actionError" class="failed" role="alert">
        <AppIcon name="alert-circle" :size="13" />
        <span>{{ translationError || actionError }}</span>
        <button class="retry-btn" @click="refreshTranslation">重试</button>
      </div>
      <div v-if="translation?.error" :class="translation.state === 'unconfigured' ? 'pending' : 'failed'" role="status">
        <AppIcon :name="translation.state === 'unconfigured' ? 'sliders' : 'alert-circle'" :size="13" />
        <span>{{ translation.error }}</span>
        <button v-if="translation.state === 'failed'" class="retry-btn" :disabled="!canRetry" @click="retry()">重新翻译</button>
      </div>
      <div v-if="translation?.state === 'waiting'" class="pending" role="status">
        <AppIcon name="languages" :size="13" />
        <span>论文等待手动开始翻译。</span>
        <button class="retry-btn" :disabled="!canRetry" @click="retry()">开始翻译</button>
      </div>
      <EmptyState v-if="!blocks.length" icon="languages" :title="message" hint="译文跟随重排视图中占据最多可见面积的页号。" />
      <div
        v-for="b in blocks"
        :key="b.id"
        class="trans-block"
        :class="{ 'is-title': ['title', 'heading'].includes(b.type) }"
      >
        <div v-if="b.type === 'equation'" class="equation-block">
          <PdfAsset v-if="b.asset" :paper-id="activeId" :block="b" :page="paperDocument?.pages?.[b.page - 1]" />
        </div>
        <PdfAsset v-else-if="b.asset" class="translation-asset" :paper-id="activeId" :block="b" :page="paperDocument?.pages?.[b.page - 1]" />
        <p v-if="b.original_only" class="dst"><RichText :text="b.src" :spans="b.caption ? b.caption_spans : b.spans" /></p>
        <p v-else-if="(mode === 'both' || translation?.state === 'waiting') && b.src" class="src"><RichText :text="b.src" :spans="b.caption ? b.caption_spans : b.spans" /></p>

        <p v-if="b.dst" class="dst"><RichText :text="b.dst" :spans="b.dst_spans" /></p>
        <div v-if="translation?.state !== 'waiting' && ['loading', 'queued'].includes(b.state)" class="pending">
          <AppIcon :name="b.state === 'loading' ? 'loader' : 'clock'" :size="13" :class="{ spin: b.state === 'loading' }" />
          <span>{{ b.state === 'loading' ? (b.retry_count ? `正在自动重试（${b.retry_count}/5）…` : '翻译中…') : translation?.state === 'unconfigured' ? '等待配置 API' : b.retry_at ? `等待自动重试（${(b.retry_count || 0) + 1}/5）…` : translation?.state === 'failed' ? '等待重试' : '等待翻译…' }}</span>
          <div v-if="translation?.state === 'translating'" class="shimmer" />
        </div>
        <div v-else-if="b.state === 'failed'" class="failed" :title="b.error">
          <AppIcon name="alert-circle" :size="13" />
          <span>翻译失败</span>
          <button class="retry-btn" :disabled="!canRetry" @click="retry(b.id)">重试</button>
        </div>

        <div class="block-actions">
          <IconButton :icon="copied === b.id ? 'check' : 'copy'" :title="copied === b.id ? '已复制' : b.original_only ? '复制原文' : '复制译文'" :size="13" :disabled="b.original_only ? !b.src : b.src ? !b.dst : !b.text" @click="copy(b)" />
          <IconButton v-if="b.src && !b.original_only && !b.local_translation" icon="rotate-cw" title="重新翻译" :size="13" :disabled="!canRetry || b.state === 'loading'" @click="retry(b.id)" />
        </div>
      </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.translation-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.trans-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  flex: none;
}
.block-count {
  font-size: 11.5px;
  color: var(--text-3);
}
.trans-body {
  contain: layout paint style;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 10px 14px;
}
.trans-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trans-block {
  position: relative;
  padding: 10px 12px;
  border-radius: var(--radius);
  border: 1px solid transparent;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.trans-block:hover {
  background: var(--surface-2);
  border-color: var(--border);
}
.is-title .dst {
  font-weight: 650;
}
.is-title .src, .is-title .dst {
  font-size: var(--reader-title-font-size, 20px);
}
.src {
  margin: 0 0 5px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-3);
}
.dst {
  margin: 0;
  font-size: var(--reader-font-size, 13.5px);
  line-height: var(--reader-line-height, 1.7);
  color: var(--text);
  white-space: pre-wrap;
}
.src, .dst { overflow-wrap: anywhere; }
.pending,
.failed {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-3);
}
.failed {
  color: var(--danger);
}
.pending > span, .failed > span { min-width: 0; overflow-wrap: anywhere; }
.failed .retry-btn { flex-shrink: 0; }
.retry-btn {
  display: inline-flex;
  align-items: center;
  height: var(--control-height);
  padding: 0 9px;
  border-radius: 99px;
  border: 1px solid color-mix(in srgb, var(--danger) 40%, transparent);
  color: var(--danger);
  font-size: 11.5px;
  transition: background-color 0.15s ease;
}
.retry-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}
.translation-asset { margin-bottom: 8px; }
.equation-block { display: flex; align-items: center; justify-content: center; gap: 16px; margin: 16px 0; }
.shimmer {
  flex: 1;
  height: 11px;
  max-width: 140px;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--surface-3) 25%, var(--surface-2) 50%, var(--surface-3) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.3s infinite;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}
.block-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.trans-block:hover .block-actions {
  opacity: 1;
}
.trans-block:focus-within .block-actions { opacity: 1; }
.block-actions .icon-btn {
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
</style>
