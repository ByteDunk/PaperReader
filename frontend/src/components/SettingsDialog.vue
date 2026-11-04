<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import IconButton from './IconButton.vue'
import ApiSettings from './ApiSettings.vue'
import RangeSetting from './RangeSetting.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import SegmentedControl from './SegmentedControl.vue'
import { requestJson } from '../services/http.js'
import { streamResponse } from '../services/sse.js'
import { clearCache, refreshPapers } from '../composables/usePapers.js'
import { refreshTranslation } from '../composables/useTranslations.js'
import { readerSettings } from '../composables/useReaderSettings.js'
import { themeMode } from '../composables/useTheme.js'

const emit = defineEmits(['close'])
const dialog = ref(null)
const settingsPanel = ref(null)
const activeSection = ref('api')
const sections = [
  { id: 'api', label: 'API 设置', icon: 'settings' },
  { id: 'translation', label: '翻译设置', icon: 'languages' },
  { id: 'display', label: '显示设置', icon: 'article' },
  { id: 'other', label: '其他设置', icon: 'sliders' },
]
const displayFields = [
  { key: 'titleFontSize', id: 'reader-title-font-size', label: '标题字号', min: 16, max: 30, unit: 'px', hint: '调整重排视图与对照翻译中的标题字号，单独控制标题的大小，便于区分章节层级。' },
  { key: 'fontSize', id: 'reader-font-size', label: '正文字号', min: 12, max: 18, unit: 'px', hint: '调整重排视图与对照翻译中的正文字号，可根据屏幕大小和阅读习惯选择合适的文字大小。' },
  { key: 'lineHeight', id: 'reader-line-height', label: '行距', min: 15, max: 22, unit: '倍', hint: '调整正文行高与字号的比例。数值越大，行间留白越多；数值越小，排版越紧凑。' },
]
const resourceFields = [
  { key: 'index_batch_size', label: '索引批量大小', min: 1, max: 16, value: 4, unit: '段', hint: '每批同时生成索引的段落数。增大可提高处理速度，也会增加峰值内存占用。' },
  { key: 'embedding_threads', label: '索引 CPU 线程', min: 1, max: 16, value: 4, unit: '个', hint: '检索模型使用的 CPU 线程数。增大可能加快索引与搜索，但会占用更多 CPU；下次推理时生效。' },
  { key: 'model_idle_minutes', label: '模型空闲释放', min: 1, max: 60, value: 5, unit: '分钟', hint: '检索模型空闲达到此时长后，自动释放模型与查询缓存以节省内存；再次使用时自动加载。' },
]
const themeOptions = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]
const saved = ref(null)
const form = ref({ base_url: '', model: '', api_key: '', auto_translate: true, translate_references: false, concurrency: 5, translation_batch_size: 10, ...Object.fromEntries(resourceFields.map(field => [field.key, field.value])) })
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const clearing = ref(false)
const cacheScope = ref('partial')
const cacheOptions = [
  { value: 'partial', label: '部分缓存' },
  { value: 'all', label: '全部缓存' },
]
const cacheHint = computed(() => cacheScope.value === 'all'
  ? '删除全部解析结果、图表、译文及索引缓存，并释放检索模型；保留原始 PDF、设置和阅读位置，需重新处理后恢复阅读。'
  : '清除页面图片和文档内存缓存，并释放检索模型；论文、译文、索引及阅读位置保留。')
const cacheNotice = ref('')
const apiError = ref('')
const settingsError = ref('')
const cacheError = ref('')
const notice = ref('')
let alive = true
let controller, testTimer, resizeObserver
const busy = computed(() => loading.value || saving.value || testing.value || clearing.value)

function syncActiveSection() {
  const panel = settingsPanel.value
  if (!panel) return
  if (panel.scrollTop > 0 && panel.scrollTop + panel.clientHeight >= panel.scrollHeight - 2) {
    activeSection.value = sections.at(-1).id
    return
  }
  const top = panel.getBoundingClientRect().top + 32
  let current = sections[0].id
  for (const { id } of sections) {
    const section = panel.querySelector(`#${id}-settings`)
    if (section?.getBoundingClientRect().top <= top) current = id
  }
  activeSection.value = current
}

function scrollToSection(id) {
  const panel = settingsPanel.value
  const section = panel?.querySelector(`#${id}-settings`)
  if (!section) return
  panel.scrollTo({
    top: panel.scrollTop + section.getBoundingClientRect().top - panel.getBoundingClientRect().top,
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
  })
}

function dismiss() {
  if (saving.value || clearing.value) return
  controller?.abort()
  dialog.value.close()
  emit('close')
}

async function clearCachedResources() {
  if (busy.value) return
  clearing.value = true
  cacheNotice.value = cacheError.value = ''
  try {
    const result = await clearCache(cacheScope.value)
    if (alive) cacheNotice.value = result.scope === 'all'
      ? '全部缓存已清理，解析结果、译文及索引已删除，可重排论文重新生成。'
      : `部分缓存已清理（${result.pages_removed} 张页面图片）。`
  } catch (exc) { if (alive) cacheError.value = exc.message }
  finally { if (alive) clearing.value = false }
}

async function persist(includeOther) {
  const payload = {
    base_url: form.value.base_url, model: form.value.model,
    api_key: form.value.api_key.trim() || null,
    revision: saved.value.revision,
  }
  if (includeOther) {
    payload.auto_translate = form.value.auto_translate
    payload.translate_references = form.value.translate_references
    payload.concurrency = form.value.concurrency
    payload.translation_batch_size = form.value.translation_batch_size
    for (const { key } of resourceFields) payload[key] = form.value[key]
  }
  const settings = await requestJson('/api/llm/settings', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!alive) return
  saved.value = settings
  if (includeOther) {
    await Promise.allSettled([refreshPapers(), refreshTranslation()])
  }
  form.value.base_url = settings.base_url
  form.value.model = settings.model
  form.value.api_key = ''
}

async function save() {
  if (busy.value || !saved.value) return
  saving.value = true
  settingsError.value = apiError.value = notice.value = ''
  try {
    await persist(true)
    if (alive) { saving.value = false; dismiss() }
  } catch (exc) { if (alive) settingsError.value = exc.message }
  finally { if (alive) saving.value = false }
}

async function testConnection() {
  if (busy.value || !saved.value) return
  saving.value = true
  apiError.value = notice.value = ''
  let timedOut = false
  try {
    await persist(false)
    if (!alive) return
    saving.value = false
    testing.value = true
    controller = new AbortController()
    testTimer = setTimeout(() => { timedOut = true; controller?.abort() }, 180000)
    await streamResponse('/api/llm/responses', { input: '请只回复：连接成功', max_output_tokens: 128 }, { signal: controller.signal })
    if (alive) notice.value = 'API 设置已保存，连接成功。'
  } catch (exc) {
    if (alive) {
      if (exc.name === 'AbortError') notice.value = timedOut ? 'API 设置已保存，连接测试超时。' : 'API 设置已保存，已停止连接测试。'
      else apiError.value = exc.message
    }
  } finally {
    clearTimeout(testTimer)
    controller = null
    if (alive) { saving.value = false; testing.value = false }
  }
}

onMounted(async () => {
  dialog.value.showModal()
  resizeObserver = new ResizeObserver(syncActiveSection)
  resizeObserver.observe(settingsPanel.value)
  for (const section of settingsPanel.value.querySelectorAll('.settings-section')) resizeObserver.observe(section)
  try {
    const settings = await requestJson('/api/llm/settings')
    if (!alive) return
    saved.value = settings
    form.value = { ...settings, api_key: '' }
  } catch (exc) { if (alive) settingsError.value = exc.message }
  finally { if (alive) loading.value = false }
})
onUnmounted(() => { alive = false; controller?.abort(); clearTimeout(testTimer); resizeObserver?.disconnect(); form.value.api_key = '' })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="settings-dialog" aria-labelledby="settings-title" @cancel.prevent="dismiss">
      <form class="settings-form" @submit.prevent="save">
        <header class="settings-header">
          <h2 id="settings-title">设置</h2>
          <IconButton icon="x" title="关闭设置" aria-label="关闭设置" :disabled="saving || clearing" @click="dismiss" />
        </header>
        <div class="settings-layout">
          <nav class="settings-nav" aria-label="设置分类">
            <button v-for="section in sections" :key="section.id" type="button" class="settings-nav-item"
              :class="{ active: activeSection === section.id }" :aria-current="activeSection === section.id ? 'location' : undefined"
              :aria-controls="`${section.id}-settings`" @click="scrollToSection(section.id)">
              <AppIcon :name="section.icon" :size="15" />{{ section.label }}
            </button>
          </nav>
          <div ref="settingsPanel" class="settings-panel" role="region" aria-label="设置内容" tabindex="0" @scroll.passive="syncActiveSection">
            <section id="api-settings" class="settings-section" aria-labelledby="api-settings-title">
              <h3 id="api-settings-title"><AppIcon name="settings" :size="16" />API 设置</h3>
              <ApiSettings v-model="form" :configured="saved?.api_key_configured" :revision="saved?.revision" :disabled="busy || !saved" />
              <div class="connection-actions">
                <button v-if="testing" type="button" class="ui-button action" @click="controller?.abort()">停止测试</button>
                <button v-else type="button" class="ui-button action" :disabled="busy || !saved" @click="testConnection">测试连接</button>
                <span v-if="testing" class="hint" role="status">等待模型响应…</span>
                <span v-else-if="apiError" class="error" role="alert">{{ apiError }}</span>
                <span v-else-if="notice" class="notice" role="status">{{ notice }}</span>
              </div>
            </section>
            <section id="translation-settings" class="settings-section" aria-labelledby="translation-settings-title">
              <h3 id="translation-settings-title"><AppIcon name="languages" :size="16" />翻译设置</h3>
              <fieldset :disabled="busy || !saved" class="settings-stack">
                <div class="toggle-setting">
                  <div>
                    <label id="auto-translate-label" for="auto-translate">导入后自动翻译</label>
                    <p id="auto-translate-hint" class="hint">开启后，导入论文会自动开始翻译；关闭后可在论文菜单中手动开始，已开始的任务会继续完成。</p>
                  </div>
                  <ToggleSwitch id="auto-translate" v-model="form.auto_translate"
                    aria-labelledby="auto-translate-label" aria-describedby="auto-translate-hint" />
                </div>
                <div class="toggle-setting">
                  <div>
                    <label id="translate-references-label" for="translate-references">翻译参考文献</label>
                    <p id="translate-references-hint" class="hint">关闭时，参考文献在对照翻译中直接显示原文。</p>
                  </div>
                  <ToggleSwitch id="translate-references" v-model="form.translate_references"
                    aria-labelledby="translate-references-label" aria-describedby="translate-references-hint" />
                </div>
                <RangeSetting id="translation-batch-size" v-model="form.translation_batch_size" label="合并翻译请求数"
                  description="每次 API 请求合并翻译的内容块数。增大可减少请求次数，但单次处理的内容也会变多；响应不稳定时可适当调小。" :min="1" :max="20" unit="块" />
                <RangeSetting id="translation-concurrency" v-model="form.concurrency" label="翻译并发数"
                  description="所有论文共享的同时翻译请求上限。增大可加快翻译，也更容易触发 API 限流；调小后，已发出的请求仍会继续完成。" :min="1" :max="30" unit="条" />
              </fieldset>
            </section>
            <section id="display-settings" class="settings-section" aria-labelledby="display-settings-title">
              <h3 id="display-settings-title"><AppIcon name="article" :size="16" />显示设置</h3>
              <p class="section-hint hint">调整后立即生效，并自动保存。</p>
              <fieldset :disabled="saving || clearing" class="settings-stack">
                <div class="theme-setting">
                  <div class="theme-copy">
                    <span id="theme-mode-label" class="setting-label">主题模式</span>
                    <p id="theme-mode-hint" class="hint">选择浅色、深色，或随系统外观自动切换。</p>
                  </div>
                  <SegmentedControl id="theme-mode" v-model="themeMode" :options="themeOptions" class="theme-control"
                    aria-labelledby="theme-mode-label" aria-describedby="theme-mode-hint" />
                </div>
                <RangeSetting v-for="field in displayFields" :key="field.key" v-model="readerSettings[field.key]"
                  :id="field.id || field.key" :label="field.label" :description="field.hint"
                  :min="field.min" :max="field.max" :unit="field.unit" :divisor="field.key === 'lineHeight' ? 10 : 1" />
                <div class="toggle-setting">
                  <div>
                    <label id="show-page-anchors-label" for="show-page-anchors">显示页锚点</label>
                    <p id="show-page-anchors-hint" class="hint">在重排视图中显示原文页码分隔，便于确认当前内容对应的 PDF 页面。</p>
                  </div>
                  <ToggleSwitch id="show-page-anchors" v-model="readerSettings.showPageAnchors"
                    aria-labelledby="show-page-anchors-label" aria-describedby="show-page-anchors-hint" />
                </div>
              </fieldset>
            </section>
            <section id="other-settings" class="settings-section" aria-labelledby="other-settings-title">
              <h3 id="other-settings-title"><AppIcon name="sliders" :size="16" />其他设置</h3>
              <fieldset :disabled="busy || !saved" class="settings-stack">
                <RangeSetting v-for="field in resourceFields" :key="field.key" v-model="form[field.key]"
                  :id="field.id || field.key" :label="field.label" :description="field.hint"
                  :min="field.min" :max="field.max" :unit="field.unit" />
              </fieldset>
              <div class="cache-actions">
                <div class="cache-copy">
                  <span class="cache-label">缓存清理</span>
                  <p id="cache-hint" class="hint">{{ cacheHint }}</p>
                </div>
                <div class="cache-controls">
                  <SegmentedControl v-model="cacheScope" :options="cacheOptions" :disabled="busy" aria-label="缓存清理范围" aria-describedby="cache-hint" />
                  <button type="button" class="ui-button action cache-clear" :disabled="busy" @click="clearCachedResources">{{ clearing ? '清理中…' : '清理缓存' }}</button>
                </div>
              </div>
            </section>
          </div>
        </div>
        <footer class="settings-footer">
          <div class="footer-status">
            <p v-if="loading" class="hint" role="status">正在读取设置…</p>
            <p v-else-if="settingsError" class="error" role="alert">{{ settingsError }}</p>
            <p v-else-if="cacheError" class="error" role="alert">{{ cacheError }}</p>
            <p v-else-if="cacheNotice" class="notice" role="status">{{ cacheNotice }}</p>
          </div>
          <div class="footer-actions">
            <button type="button" class="ui-button action" :disabled="saving || clearing" @click="dismiss">取消</button>
            <button type="submit" class="ui-button ui-button--primary action" :disabled="busy || !saved">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </footer>
      </form>
    </dialog>
  </Teleport>
</template>

<style scoped>
.settings-dialog { width: min(820px, calc(100vw - 32px)); height: min(740px, calc(100dvh - 48px)); max-height: calc(100dvh - 48px); padding: 0; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); color: var(--text); box-shadow: var(--shadow-md); overflow: hidden; }
.settings-dialog::backdrop { background: rgba(15, 18, 28, .46); backdrop-filter: blur(3px); }
.settings-form { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.settings-header { display: flex; align-items: flex-start; justify-content: space-between; padding: 16px 24px 14px; border-bottom: 1px solid var(--border); flex: none; }
h2 { margin: 0; font-size: 20px; font-weight: 650; line-height: 1.3; }
.settings-layout { display: grid; grid-template-columns: 152px minmax(0, 1fr); flex: 1; min-height: 0; }
.settings-nav { display: flex; flex-direction: column; gap: 6px; padding: 16px 12px; border-right: 1px solid var(--border); background: var(--surface-2); overflow-y: auto; }
.settings-nav-item { display: flex; align-items: center; gap: 8px; flex: none; width: 100%; padding: 9px 10px; border-radius: var(--radius-s); color: var(--text-2); font-size: 12.5px; text-align: left; transition: background-color .15s ease, color .15s ease; }
.settings-nav-item:hover { background: var(--surface-3); color: var(--text); }
.settings-nav-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 550; }
.settings-nav-item svg { flex: none; }
.settings-panel { min-width: 0; min-height: 0; padding: 0 24px; overflow-y: auto; overscroll-behavior: contain; }
.settings-panel:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.settings-section { min-width: 0; padding: 22px 0 24px; }
.settings-section + .settings-section { border-top: 1px solid var(--border); }
h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; padding-bottom: 8px; font-size: 14px; font-weight: 600; }
h3 svg { color: var(--text-2); }
.settings-stack { display: flex; flex-direction: column; gap: 18px; border: 0; padding: 0; margin: 0; min-width: 0; }
.theme-setting { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; }
.theme-copy { flex: 1 1 160px; min-width: 0; }
.theme-control { margin-left: auto; }
.connection-actions { display: flex; align-items: center; gap: 10px; margin: 18px 0 0; }
.connection-actions .action { width: 98px; }
.connection-actions > span { min-width: 0; flex: 1; }
.toggle-setting { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.toggle-setting label, .setting-label { display: block; margin-bottom: 4px; color: var(--text); font-size: 12.5px; font-weight: 550; }
.toggle-setting label { cursor: pointer; }
.toggle-setting .hint, .theme-setting .hint { color: var(--text-3); font-size: 11px; line-height: 1.65; }
.cache-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 18px; }
.cache-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; width: 100%; }
.cache-clear { margin-left: auto; border-color: var(--danger); color: var(--danger); }
.cache-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.cache-label { color: var(--text); font-size: 12.5px; font-weight: 550; line-height: 1.55; }
.cache-copy .hint { color: var(--text-3); font-size: 11px; line-height: 1.65; }
.hint { margin: 0; color: var(--text-2); font-size: 11.5px; line-height: 1.7; }
.section-hint { margin: -6px 0 16px; }
.notice { margin: 0; color: var(--success); font-size: 12px; }
.settings-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 12px 24px; border-top: 1px solid var(--border); flex: none; }
.footer-status { min-width: 0; }
.error { margin: 0; color: var(--danger); font-size: 12px; overflow-wrap: anywhere; }
.footer-actions { display: flex; gap: 10px; flex: none; }
.footer-actions .action { width: 80px; }
@media (max-width: 640px) {
  .settings-layout { grid-template-columns: 120px minmax(0, 1fr); }
  .settings-nav { padding: 14px 8px; }
  .settings-nav-item { gap: 6px; padding: 9px 8px; font-size: 12px; }
  .settings-panel { padding: 0 18px; }
  .settings-header { padding: 16px 18px 14px; }
  .settings-footer { padding: 12px 18px; gap: 12px; }
}
@media (max-width: 420px) {
  .settings-dialog { width: calc(100vw - 16px); height: calc(100dvh - 24px); max-height: calc(100dvh - 24px); }
  .settings-layout { grid-template-columns: 94px minmax(0, 1fr); }
  .settings-nav { padding: 12px 6px; }
  .settings-nav-item { justify-content: center; gap: 0; padding: 9px 4px; }
  .settings-nav-item svg { display: none; }
  .settings-panel { padding: 0 12px; }
  .settings-footer { align-items: flex-end; }
  .footer-actions .action { width: 60px; }
}
@media (prefers-reduced-motion: reduce) {
  .settings-nav-item { transition: none; }
}
</style>
