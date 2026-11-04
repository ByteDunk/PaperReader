<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import IconButton from '../components/IconButton.vue'
import AssistantAnswer from '../components/AssistantAnswer.vue'
import { activeId, activePaper, reading, selectPaper, locateSource, invalidatedPaper } from '../composables/usePapers.js'
import { streamAssistant, stopAssistantRun } from '../services/assistantConnection.js'
import { applyAssistantEvent, assistantPage, finishAssistantMessage, restoreAssistantMessage, toolLabels, assistantHistory, assistantMessageContent } from '../services/assistant.js'
import { presentAnswer } from '../services/answerFormatting.js'
import { assistantDraft, assistantDrafts, removeAssistantReference } from '../composables/useAssistantDrafts.js'
import { layout } from '../dock/useLayout.js'

const quickPrompts = ['总结这篇论文', '解释当前页内容', '本文的创新点', '列出本文的局限']
const chats = ref({})
const messages = computed(() => chats.value[activeId.value] || [])
const draft = computed({ get: () => assistantDrafts[activeId.value]?.text || '',
  set: value => { if (activeId.value) assistantDraft(activeId.value).text = value } })
const attachedReferences = computed(() => assistantDrafts[activeId.value]?.references || [])
const referenceNotice = computed(() => assistantDrafts[activeId.value]?.notice || '')
const input = ref(null)
const busy = ref(false)
const messageBox = ref(null)
const notice = ref('')
const now = ref(Date.now())
let followOutput = true
let waitingTimer
let controller
let requestId
let generation = 0
const storageKey = 'paperreader.assistant.v1'
try {
  const saved = JSON.parse(localStorage.getItem(storageKey) || '{}')
  if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
    for (const [id, items] of Object.entries(saved)) {
      if (!Array.isArray(items)) continue
      chats.value[id] = items.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.text === 'string')
        .map(restoreAssistantMessage)
    }
  }
} catch { /* corrupt or unavailable browser storage */ }
function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify(chats.value)) }
  catch { notice.value = '浏览器存储空间不足，本次对话仅保留在当前会话。' }
}
function stop() {
  clearInterval(waitingTimer)
  controller?.abort()
  if (requestId) void stopAssistantRun(requestId)
  requestId = null
  controller = null
  generation++
  for (const items of Object.values(chats.value)) for (const m of items) {
    if (m.pending) { finishAssistantMessage(m); m.error = '已停止生成。' }
  }
  busy.value = false
  persist()
}
watch(activeId, () => { stop(); notice.value = '' })
watch(invalidatedPaper, value => {
  if (!value) return
  if (value.id === activeId.value) stop()
  delete chats.value[value.id]
  delete assistantDrafts[value.id]
  persist()
})
onBeforeUnmount(stop)
function focusInput() { if (attachedReferences.value.length) nextTick(() => input.value?.focus()) }
onActivated(focusInput)
watch(() => attachedReferences.value.length, focusInput)
async function scroll() {
  await nextTick()
  const el = messageBox.value
  if (el && followOutput) el.scrollTop = el.scrollHeight
}
function trackScroll() {
  const el = messageBox.value
  if (el) followOutput = el.scrollHeight - el.clientHeight - el.scrollTop < 60
}
async function send(question = draft.value, retryIndex = null) {
  if (busy.value || activePaper.value?.state !== 'ready') return
  const id = activeId.value
  if (!chats.value[id]) chats.value[id] = []
  const items = chats.value[id]
  const references = retryIndex !== null ? (items.slice(0, retryIndex).findLast(m => m.role === 'user')?.references || []) : attachedReferences.value
  const questionText = question.trim() || (references.length ? '请解释这些论文引用。' : '')
  if (!questionText) return
  const userMessage = { role: 'user', text: questionText, references: references.map(reference => ({ ...reference })) }
  if (assistantMessageContent(userMessage).length > 20000) { notice.value = '问题和引用内容过长，请缩短问题或减少附加引用。'; return }
  notice.value = ''
  if (retryIndex !== null) items.splice(retryIndex)
  else items.push(userMessage)
  const history = assistantHistory(items)
  items.push({ role: 'assistant', text: '', trace: [], sources: [], pending: true, error: '',
    status: '正在发送问题…', startedAt: Date.now() })
  const answer = items[items.length - 1]
  if (retryIndex === null) { draft.value = ''; assistantDraft(id).references = []; assistantDraft(id).notice = '' }
  busy.value = true
  now.value = Date.now()
  waitingTimer = setInterval(() => { now.value = Date.now() }, 1000)
  const token = ++generation
  controller = new AbortController()
  requestId = crypto.randomUUID()
  const runId = requestId
  followOutput = true
  scroll()
  try {
    await streamAssistant({ request_id: runId, paper_id: id,
      page: assistantPage(reading[id], layout.columns),
      messages: history }, { signal: controller.signal,
      onEvent(event) {
        if (token !== generation) return
        applyAssistantEvent(answer, event)
        scroll()
      },
    })
  } catch (error) {
    if (token === generation) answer.error = error.name === 'AbortError' ? '已停止生成。' : error.message
  } finally {
    finishAssistantMessage(answer)
    if (token === generation) { clearInterval(waitingTimer); busy.value = false; controller = null; requestId = null }
    persist()
  }
}
function retry(index) {
  const question = messages.value.slice(0, index).findLast(m => m.role === 'user')?.text
  if (question) send(question, index)
}
async function navigate(source) {
  if (!source) return
  if (source.paper_id !== activeId.value) await selectPaper(source.paper_id)
  locateSource(source)
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); notice.value = '已复制。' }
  catch { notice.value = '复制失败，请手动选择文本复制。' }
}
function clearChat() { if (!busy.value) { delete chats.value[activeId.value]; persist() } }
function keydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send() }
}
</script>

<template>
  <div class="assistant">
    <div class="quick-prompts">
      <button v-for="q in quickPrompts" :key="q" class="chip" :disabled="busy || activePaper?.state !== 'ready'" @click="send(q)">{{ q }}</button>
    </div>
    <div ref="messageBox" class="messages" aria-live="polite" @scroll="trackScroll">
      <p v-if="!messages.length" class="assistant-hint">{{ activePaper?.state === 'ready' ? '就这篇论文提问。助手会自主查阅章节、检索证据，并提供可定位的引用。' : '请先选择一篇已完成解析的论文。' }}</p>
      <div v-for="(message, index) in messages" :key="index" class="msg" :class="message.role === 'user' ? 'user' : 'ai'">
        <template v-if="message.role === 'user'">
          <p>{{ message.text }}</p>
          <button v-for="reference in message.references || []" :key="reference.id" class="message-reference" :title="reference.text" @click="navigate(reference)">
            <AppIcon name="quote" :size="12" />第 {{ reference.page }} 页{{ reference.truncated ? '（节选）' : '' }} · {{ reference.text || '论文内容块' }}
          </button>
        </template>
        <template v-else>
          <span class="ai-avatar"><AppIcon name="sparkles" :size="13" /></span>
          <div class="ai-content">
            <details v-if="message.trace.length" class="assistant-card agent-trace" :open="message.pending">
              <summary class="assistant-card-title">执行过程 · {{ message.trace.filter(entry => entry.type === 'tool').length }} 次工具调用</summary>
              <details v-for="entry in message.trace" :key="`${entry.type}:${entry.id}`" class="trace-entry" :open="entry.type === 'output' && entry.status === 'streaming' && message.pending">
                <summary>
                  {{ entry.type === 'output' ? '模型输出' : (toolLabels[entry.name] || entry.name) }}
                  <template v-if="entry.round"> · 第 {{ entry.round }} 轮</template>
                  · {{ ['streaming', 'running'].includes(entry.status) ? '进行中' : entry.status === 'stopped' ? '已停止' : entry.status === 'error' ? '未完成' : '完成' }}
                </summary>
                <p v-if="entry.type === 'output'" class="trace-text">{{ entry.text }}</p>
                <template v-else>
                  <pre>{{ entry.arguments }}</pre>
                  <pre v-if="entry.result">{{ JSON.stringify(entry.result, null, 2) }}</pre>
                </template>
              </details>
            </details>
            <AssistantAnswer :text="message.text" :sources="message.sources" @navigate="navigate" />
            <span v-if="message.pending" class="cursor" />
            <p v-if="message.pending" class="assistant-hint" role="status">
              {{ message.status }} · {{ Math.max(0, Math.floor((now - message.startedAt) / 1000)) }} 秒
              <template v-if="now - message.startedAt >= 15000 && !message.text && !message.trace.length">模型尚未返回内容，可继续等待或停止。</template>
            </p>
            <p v-if="message.error" class="assistant-hint" role="alert">{{ message.error }}</p>
            <div class="msg-actions">
              <IconButton icon="copy" title="复制" :size="13" :disabled="!message.text" @click="copy(presentAnswer(message.text, message.sources).text)" />
              <IconButton icon="rotate-cw" title="重新生成（替换此条及后续对话）" :size="13" :disabled="busy" @click="retry(index)" />
            </div>
          </div>
        </template>
      </div>
      <p v-if="notice" class="assistant-hint" role="status">{{ notice }}</p>
    </div>
    <div v-if="attachedReferences.length" class="draft-references">
      <div v-for="reference in attachedReferences" :key="reference.id" class="draft-reference">
        <button class="reference-preview" :title="reference.text" @click="navigate(reference)"><AppIcon name="quote" :size="12" /><span>第 {{ reference.page }} 页{{ reference.truncated ? '（节选）' : '' }} · {{ reference.text || '论文内容块' }}</span></button>
        <IconButton icon="x" title="移除引用" :size="12" @click="removeAssistantReference(activeId, reference.id)" />
      </div>
    </div>
    <p v-if="referenceNotice" class="assistant-hint reference-notice" role="status">{{ referenceNotice }}</p>
    <footer class="composer">
      <textarea ref="input" v-model="draft" class="ui-textarea" rows="2" maxlength="20000" aria-label="向论文助手提问" :placeholder="attachedReferences.length ? '针对附加引用提问…（Enter 发送）' : '就这篇论文提问…（Enter 发送）'" @keydown="keydown" />
      <div class="composer-actions">
        <IconButton icon="trash" title="清空当前对话" :size="13" :disabled="busy || !messages.length" @click="clearChat" />
        <button v-if="busy" class="ui-button ui-button--primary send-btn" title="停止生成" aria-label="停止生成" @click="stop">■</button>
        <button v-else class="ui-button ui-button--primary send-btn" title="发送" aria-label="发送" :disabled="(!draft.trim() && !attachedReferences.length) || activePaper?.state !== 'ready'" @click="send()"><AppIcon name="send" :size="15" /></button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.assistant {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  flex: none;
}
.chip {
  height: var(--control-height);
  padding: 0 11px;
  border-radius: 99px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-2);
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}
.chip:hover:not(:disabled) {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-soft);
}
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.msg.user {
  align-self: flex-end;
  max-width: 86%;
}
.msg.user p {
  margin: 0;
  padding: 8px 13px;
  border-radius: 13px 13px 4px 13px;
  background: var(--accent);
  color: var(--on-accent);
  font-size: 13px;
  line-height: 1.6;
}
.msg.ai {
  display: flex;
  gap: 9px;
  align-items: flex-start;
}
.ai-avatar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: var(--accent-soft);
  color: var(--accent);
  margin-top: 2px;
}
.ai-content {
  min-width: 0;
  flex: 1;
}
.ai-content p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.7;
}
.cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--accent);
  border-radius: 1px;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.msg-actions {
  display: flex;
  gap: 2px;
  margin-top: 8px;
}
.composer {
  flex: none;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--border);
}
.composer textarea {
  flex: 1;
  align-self: stretch;
  resize: none;
}
.composer-actions { display: flex; flex-direction: column; align-items: center; gap: 6px; flex: none; }
.draft-references { flex: none; max-height: 140px; overflow-y: auto; padding: 6px 12px 0; border-top: 1px solid var(--border); }
.draft-reference { display: flex; align-items: center; gap: 4px; padding: 3px 6px; margin-bottom: 4px; border-radius: var(--radius-s); background: var(--surface-2); }
.reference-preview { display: flex; align-items: center; gap: 5px; min-width: 0; flex: 1; color: var(--accent); font-size: 11.5px; text-align: left; }
.reference-preview span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.message-reference { display: block; max-width: 100%; margin: 5px 0 0 auto; color: var(--accent); font-size: 11.5px; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.reference-notice { margin: 4px 12px; }
.send-btn {
  width: var(--control-height);
  padding: 0;
}
.assistant-hint { color: var(--text-3); font-size: 12px; line-height: 1.7; }
.agent-trace summary { cursor: pointer; }
.trace-entry { color: var(--text-2); font-size: 12px; margin: 8px 0; }
.trace-entry:last-child { margin-bottom: 0; }
.trace-entry pre { margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; font-size: 11px; }
.ai-content .trace-text { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; margin: 6px 0 0; }
</style>
