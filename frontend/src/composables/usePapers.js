import { computed, reactive, readonly, ref, shallowRef } from 'vue'
import { openPanel } from '../dock/useLayout.js'
import { paperApi as api } from '../services/http.js'
import { resolveSourceBlock } from '../services/reflowGeometry.js'

const STORAGE_KEY = 'paperreader.reading'
const CACHE_LIMIT = 3
const CACHE_CHARACTER_LIMIT = 4_000_000
let saved = {}
try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {} } catch { /* recover invalid state */ }

const scrolling = ref(false)
let settleTimer

export const reflowScrolling = readonly(scrolling)

// Publish only the edges of a scroll burst, not a reactive update every frame.
// The timer also covers smooth scrolling and browsers without scrollend.
export function markReflowScroll() {
  scrolling.value = true
  clearTimeout(settleTimer)
  settleTimer = setTimeout(finishReflowScroll, 140)
}

export function finishReflowScroll() {
  clearTimeout(settleTimer)
  settleTimer = undefined
  scrolling.value = false
}

export const papers = ref([])
export const activeId = ref(saved.activeId || '')
export const activePaper = computed(() => papers.value.find(p => p.id === activeId.value))
export const document = shallowRef(null)
export const invalidatedPaper = shallowRef(null)
export const importing = ref(false)
export const loading = ref(false)
export const error = ref('')
export const reading = reactive(saved.positions || {})
export const sourceTarget = ref(null)
export const reflowTarget = ref(null)
export const paperActions = reactive({})
const cache = new Map()
let cacheSize = 0
let cacheVersion = 0
let lifecycleVersion = 0
let initialized = false
let selectionVersion = 0
let refreshVersion = 0
let pollTimer
let documentController
let pollController
let persistTimer
let readingDirty = false

function forgetDocument(id) {
  const entry = cache.get(id)
  if (entry) cacheSize -= entry.size
  cache.delete(id)
}

function clearDocuments() {
  cache.clear()
  cacheSize = 0
}

function cachedDocument(id) {
  const entry = cache.get(id)
  if (!entry) return null
  cache.delete(id)
  cache.set(id, entry)
  return entry.document
}

function cacheDocument(id, value) {
  forgetDocument(id)
  const size = JSON.stringify(value).length
  // Large documents remain readable through the active ref without retaining
  // another library-wide cache entry after the reader switches papers.
  if (size > CACHE_CHARACTER_LIMIT) return
  cache.set(id, { document: value, size })
  cacheSize += size
  while (cache.size > CACHE_LIMIT || cacheSize > CACHE_CHARACTER_LIMIT) forgetDocument(cache.keys().next().value)
}

export async function clearCache(scope = 'partial') {
  const lifecycle = lifecycleVersion
  const result = await api(`/cache?scope=${encodeURIComponent(scope)}`, { method: 'POST' })
  if (lifecycle !== lifecycleVersion) return result
  ++cacheVersion
  clearDocuments()
  if (result.scope === 'all') {
    ++refreshVersion
    invalidatePaper(activeId.value, false, true)
    await refreshPapers()
  }
  return result
}

function persist() {
  clearTimeout(persistTimer)
  persistTimer = undefined
  readingDirty = false
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ activeId: activeId.value, positions: reading })) }
  catch { /* reading remains available without browser storage */ }
}

export function flushReading() {
  if (readingDirty) persist()
}

// Keep live positions synchronous, but serialize only once after a burst of
// scrolling. Flush before leaving the page so refresh/navigation restore them.
function onVisibilityChange() {
  if (window.document.visibilityState === 'hidden') flushReading()
}

export function updateReading(patch) {
  if (!activeId.value) return
  const position = reading[activeId.value] ||= {}
  const entries = Object.entries(patch)
  if (entries.length && entries.every(([key, value]) => position[key] === value)) return
  Object.assign(position, patch, { lastRead: Date.now() })
  readingDirty = true
  clearTimeout(persistTimer)
  persistTimer = setTimeout(flushReading, 250)
}

export async function selectPaper(id) {
  flushReading()
  documentController?.abort()
  documentController = null
  const version = ++selectionVersion
  activeId.value = id
  document.value = activePaper.value?.state === 'ready' ? cachedDocument(id) : null
  sourceTarget.value = null
  reflowTarget.value = null
  error.value = ''
  updateReading({})
  const paper = activePaper.value
  loading.value = paper?.state === 'ready' && !document.value
  if (!loading.value) return
  try {
    const controller = documentController = new AbortController()
    const currentCacheVersion = cacheVersion
    const result = await api(`/${id}/reflow`, { signal: controller.signal })
    if (version === selectionVersion) {
      if (currentCacheVersion === cacheVersion) cacheDocument(id, result)
      document.value = result
    }
  } catch (e) {
    if (version === selectionVersion && e.name !== 'AbortError') error.value = e.message
  } finally {
    if (version === selectionVersion) { loading.value = false; documentController = null }
  }
}

export async function refreshPapers() {
  const version = ++refreshVersion
  clearTimeout(pollTimer)
  pollController?.abort()
  const controller = pollController = new AbortController()
  let result
  try { result = await api('', { signal: controller.signal }) }
  catch (e) { if (e.name === 'AbortError' || version !== refreshVersion) return; throw e }
  finally { if (pollController === controller) pollController = null }
  if (version !== refreshVersion) return
  papers.value = result
  if (!activePaper.value && !papers.value.length) {
    ++selectionVersion
    activeId.value = ''
    document.value = null
    sourceTarget.value = null
    reflowTarget.value = null
    loading.value = false
    persist()
  }
  if (!activePaper.value && papers.value.length) await selectPaper(papers.value[0].id)
  else if (activePaper.value?.state === 'ready' && !document.value && !loading.value) await selectPaper(activeId.value)
  if (version !== refreshVersion) return
  if (papers.value.some(p => p.state === 'parsing' || ['translating', 'unconfigured'].includes(p.translation?.state)
    || ['indexing', 'queued'].includes(p.index?.state))) {
    pollTimer = setTimeout(() => {
      const lifecycle = lifecycleVersion
      refreshPapers().catch(e => { if (lifecycle === lifecycleVersion) error.value = e.message })
    }, 1500)
  }
}

export async function initializePapers() {
  if (initialized) return
  initialized = true
  const lifecycle = lifecycleVersion
  window.addEventListener('pagehide', flushReading)
  window.document.addEventListener('visibilitychange', onVisibilityChange)
  try {
    await refreshPapers()
  }
  catch (e) {
    if (lifecycle === lifecycleVersion) { error.value = e.message; initialized = false }
  }
}

export function disposePapers() {
  flushReading()
  ++lifecycleVersion
  ++selectionVersion
  ++refreshVersion
  ++cacheVersion
  initialized = false
  clearTimeout(pollTimer)
  clearTimeout(persistTimer)
  documentController?.abort()
  pollController?.abort()
  documentController = pollController = null
  window.removeEventListener('pagehide', flushReading)
  window.document.removeEventListener('visibilitychange', onVisibilityChange)
  finishReflowScroll()
  clearDocuments()
  papers.value = []
  document.value = sourceTarget.value = reflowTarget.value = null
  importing.value = loading.value = false
  error.value = ''
  for (const id of Object.keys(paperActions)) delete paperActions[id]
}

if (import.meta.hot) import.meta.hot.dispose(disposePapers)

export async function importPapers(files) {
  if (importing.value || !files.length) return
  const lifecycle = lifecycleVersion
  importing.value = true
  error.value = ''
  const failures = []
  try {
    for (const file of files) {
      if (lifecycle !== lifecycleVersion) return
      try {
        const form = new FormData()
        form.append('file', file)
        const paper = await api('', { method: 'POST', body: form })
        if (lifecycle !== lifecycleVersion) return
        ++refreshVersion
        papers.value = [paper, ...papers.value.filter(p => p.id !== paper.id)]
        await selectPaper(paper.id)
        if (lifecycle !== lifecycleVersion) return
      } catch (e) { failures.push(`${file.name}：${e.message}`) }
    }
    if (lifecycle === lifecycleVersion) await refreshPapers()
  } catch (e) { failures.push(e.message) }
  finally {
    if (lifecycle === lifecycleVersion) { error.value = failures.join('；'); importing.value = false }
  }
}

function invalidatePaper(id, deleted = false, cleared = false) {
  forgetDocument(id)
  invalidatedPaper.value = { id, deleted, cleared }
  if (id === activeId.value) {
    documentController?.abort()
    documentController = null
    ++selectionVersion
    document.value = null
    sourceTarget.value = null
    reflowTarget.value = null
    loading.value = false
  }
}

async function withPaperAction(id, action, operation) {
  if (paperActions[id]) return false
  const lifecycle = lifecycleVersion
  const current = () => lifecycle === lifecycleVersion
  paperActions[id] = action
  error.value = ''
  ++refreshVersion
  try {
    await operation(current)
    return current()
  } catch (e) { if (current()) error.value = e.message; return false }
  finally { if (current()) delete paperActions[id] }
}

function replacePaper(paper) {
  ++refreshVersion
  papers.value = papers.value.map(p => p.id === paper.id ? paper : p)
}

export function deletePaper(id) {
  return withPaperAction(id, 'deleting', async current => {
    await api(`/${id}`, { method: 'DELETE' })
    if (!current()) return
    ++refreshVersion // Reject polls started while the deletion was in flight.
    invalidatePaper(id, true)
    delete reading[id]
    papers.value = papers.value.filter(p => p.id !== id)
    if (activeId.value === id) {
      activeId.value = ''
      if (papers.value.length) await selectPaper(papers.value[0].id)
    }
    if (current()) persist()
  })
}

export function reparsePaper(id) {
  return withPaperAction(id, 'reparsing', async current => {
    const paper = await api(`/${id}/reparse`, { method: 'POST' })
    if (!current()) return
    replacePaper(paper)
    invalidatePaper(id)
    if (activeId.value === id) {
      updateReading({ reflowBlock: '', reflowOffset: 0, reflowPage: 1, reflowPageProgress: 0, progress: 0 })
    }
    await refreshPapers()
  })
}

export function retranslatePaper(id, blockId = null, failedOnly = false) {
  return withPaperAction(id, 'translating', async current => {
    const paper = await api(`/${id}/translation`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ block_id: blockId, failed_only: failedOnly }),
    })
    if (!current()) return
    replacePaper(paper)
    await refreshPapers()
  })
}

export function reindexPaper(id) {
  const current = papers.value.find(p => p.id === id)
  if (!current || current.state !== 'ready' || current.index?.state === 'indexing') return false
  return withPaperAction(id, 'indexing', async current => {
    const paper = await api(`/${id}/index`, { method: 'POST' })
    if (!current()) return
    replacePaper(paper)
    await refreshPapers()
  })
}

export function locateSource(block) {
  sourceTarget.value = { paperId: activeId.value, page: block.page, bbox: block.bbox, id: block.block_id || block.id }
  updateReading({ page: block.page })
  openPanel('original')
}

export function locateReflow() {
  const target = sourceTarget.value
  if (!target || target.paperId !== activeId.value) return
  const block = resolveSourceBlock(document.value?.blocks || [], target)
  if (!block) return
  reflowTarget.value = { paperId: target.paperId, id: block.id }
  openPanel('reflow')
}
