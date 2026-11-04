<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppTopBar from './AppTopBar.vue'
import AppIcon from './AppIcon.vue'
import { closeDesktopApp, downloadDesktopModels } from '../services/desktop.js'

const props = defineProps({ state: { type: Object, required: true } })
const prompt = ref(null)
const actionError = ref('')
const submitting = ref(false)
const downloading = computed(() => ['downloading', 'pausing', 'paused', 'download_error'].includes(props.state.phase))
const paused = computed(() => ['paused', 'download_error'].includes(props.state.phase))
const pausing = computed(() => props.state.phase === 'pausing')
const missingBytes = computed(() => props.state.groups.reduce((sum, group) => sum + group.total_bytes, 0))
function modelProgress(model) {
  const total = model.total_bytes
  return total ? Math.min(100, Math.max(0, (model.downloaded_bytes || 0) / total * 100)) : 100
}
function remainingText(model) {
  if (model.stage === 'verified' || !model.total_bytes) return '已完成'
  if (model.stage === 'failed') return '下载失败'
  if (paused.value) return '下载已暂停'
  if (pausing.value) return '正在暂停下载…'
  if (model.stage === 'verifying') return '正在校验文件…'
  if (model.stage === 'retrying') return '连接中断，正在重试…'
  const seconds = model.remaining_seconds
  if (!Number.isFinite(seconds)) return '正在估算剩余时间'
  if (seconds < 1) return '即将完成'
  const minutes = Math.ceil(seconds / 60)
  return minutes < 60 ? `剩余约 ${minutes} 分钟` : `剩余约 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
}

function bytes(value = 0) {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${Math.round(value / 1024)} KB`
}
watch(() => props.state.phase, async phase => {
  await nextTick()
  if (phase === 'confirm' && prompt.value && !prompt.value.open) prompt.value.showModal()
  else if (phase !== 'confirm' && prompt.value?.open) prompt.value.close()
}, { immediate: true })

async function download(pause = false) {
  if (submitting.value || pausing.value) return
  submitting.value = true
  actionError.value = ''
  try { await downloadDesktopModels(pause) }
  catch (error) { actionError.value = String(error?.message || error) }
  finally { submitting.value = false }
}
async function cancel() {
  try { await closeDesktopApp() }
  catch (error) { actionError.value = `无法退出应用：${error?.message || error}` }
}
</script>

<template>
  <div class="startup-shell">
    <AppTopBar :ready="false" />
    <main v-if="downloading" class="setup-main">
      <section class="setup-card" aria-labelledby="setup-title">
        <header>
          <h1 id="setup-title">准备本地模型</h1>
          <p class="setup-subtitle">{{ paused ? '下载已暂停，点击继续下载可从当前进度恢复。' : '正在从 ModelScope 下载模型。下载完成后，自动进入主界面。' }}</p>
        </header>
        <div class="download-body">
          <div v-for="model in state.groups" :key="model.id" class="model-download">
            <div class="progress-heading">
              <p class="model-title">{{ model.title }}</p>
              <output>{{ modelProgress(model).toFixed(1) }}<span>%</span></output>
            </div>
            <div class="download-track" role="progressbar" :aria-label="`${model.title}下载进度`" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.round(modelProgress(model))">
              <i :style="{ width: `${modelProgress(model)}%` }" />
            </div>
            <div class="download-metrics">
              <span>{{ bytes(model.downloaded_bytes) }} / {{ bytes(model.total_bytes) }}</span>
              <div class="transfer-status">
                <span>{{ bytes(paused || pausing ? 0 : model.bytes_per_second) }}/s</span>
                <span>{{ remainingText(model) }}</span>
              </div>
            </div>
          </div>
        </div>
        <p v-if="state.error || actionError" class="error download-error" role="alert">{{ actionError || state.error }}</p>
        <footer class="setup-footer">
          <button class="ui-button download-toggle" :disabled="submitting || pausing" @click="download(!paused)">{{ pausing ? '正在暂停…' : paused ? '继续下载' : '暂停下载' }}</button>
          <button class="ui-button" @click="cancel">取消并退出</button>
        </footer>
      </section>
    </main>
    <p v-else class="startup-message" :role="state.error ? 'alert' : 'status'">{{ state.error || '正在打开资料库…' }}</p>
    <dialog ref="prompt" class="model-prompt" aria-labelledby="prompt-title" aria-describedby="prompt-description" @cancel.prevent="cancel">
      <div class="prompt-body">
        <div class="setup-mark"><AppIcon name="database" :size="23" /></div>
        <h2 id="prompt-title">需要下载本地模型</h2>
        <p id="prompt-description">当前应用未携带完整模型，需要从 ModelScope 下载约 {{ bytes(missingBytes) }} 的文件，用于文档解析与语义检索。点击确定开始下载，取消将退出应用。</p>
        <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
      </div>
      <div class="prompt-actions">
        <button class="ui-button" @click="cancel">取消</button>
        <button class="ui-button ui-button--primary" :disabled="submitting" autofocus @click="download()">确定</button>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.startup-shell { height: 100%; display: flex; flex-direction: column; }
.startup-message { margin: 0; padding: 48px; line-height: 1.8; white-space: pre-wrap; user-select: text; }
.setup-main { display: grid; place-items: center; flex: 1; min-height: 0; padding: 32px; overflow-y: auto; background: var(--bg); }
.setup-card { width: min(620px, 100%); padding: 28px 36px; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow-md); }
.setup-subtitle { margin-top: 10px; color: var(--text-2); font-size: 13px; line-height: 1.6; }
.setup-mark { display: grid; place-items: center; flex: none; width: 44px; height: 44px; border-radius: var(--radius); background: var(--accent-soft); color: var(--accent); }
h1, h2, p { margin: 0; }
h1 { font-size: 27px; font-weight: 600; line-height: 1.4; letter-spacing: -.02em; }
.download-body { margin-top: 28px; }
.model-download + .model-download { margin-top: 28px; }
.model-title { min-width: 0; font-size: 13px; line-height: 1.65; }
.progress-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
output { flex: none; color: var(--accent); font-size: 24px; font-weight: 500; line-height: 1.2; font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
output > span { margin-left: 2px; font-size: 14px; }
.download-track { height: 6px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.download-track > i { display: block; height: 100%; border-radius: inherit; background: var(--accent); transition: width .2s ease; }
.download-metrics, .transfer-status { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.download-metrics { margin-top: 14px; color: var(--text-2); font-size: 11.5px; font-variant-numeric: tabular-nums; line-height: 1.7; }
.transfer-status { justify-content: flex-end; flex-wrap: wrap; gap: 4px 14px; }
.setup-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
.setup-footer .ui-button { min-width: 92px; height: 34px; }
.setup-footer .download-toggle { margin-right: auto; }
.error { color: var(--danger); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; user-select: text; }
.download-error { margin-top: 20px; }
.model-prompt { width: min(460px, calc(100vw - 48px)); padding: 0; border: 1px solid var(--border); border-radius: var(--radius-l); background: var(--surface); color: var(--text); box-shadow: var(--shadow-md); }
.model-prompt::backdrop { background: rgba(0, 0, 0, .35); backdrop-filter: blur(4px); }
.prompt-body { display: flex; flex-direction: column; align-items: flex-start; gap: 16px; padding: 26px; }
.prompt-body h2 { font-size: 18px; }
#prompt-description { color: var(--text-2); font-size: 12.5px; line-height: 1.8; }
.prompt-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 24px; border-top: 1px solid var(--border); }
.prompt-actions button { min-width: 76px; }
@media (max-width: 520px) {
  .setup-main { padding: 20px; }
  .setup-card { padding: 24px; }
  h1 { font-size: 24px; }
  .download-metrics { align-items: flex-start; }
  .transfer-status { column-gap: 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .download-track > i { transition: none; }
}
</style>
