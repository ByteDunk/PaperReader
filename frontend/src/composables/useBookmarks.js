import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { requestJson } from '../services/http.js'
import { activeId, document, invalidatedPaper, papers } from './usePapers.js'
import { resolveSourceBlock } from '../services/reflowGeometry.js'
import { openPanel } from '../dock/useLayout.js'

export const bookmarks = ref([])
export const bookmarksLoading = ref(false)
export const bookmarksError = ref('')
export const bookmarkActions = reactive({})
export const bookmarkEditor = shallowRef(null)
export const bookmarkSaving = ref(false)
export const bookmarkEditorError = ref('')
export const bookmarkIndex = computed(() => {
  const entries = new Map()
  for (const item of bookmarks.value) {
    const blockId = item.paper_id === activeId.value && document.value
      ? resolveSourceBlock(document.value.blocks, { ...item, id: item.block_id })?.id
      : item.block_id
    if (blockId) entries.set(`${item.paper_id}/${blockId}`, item)
  }
  return entries
})
let initialized = false
let pendingLoad = null
let revision = 0

function api(path = '', options) {
  return requestJson(`/api/bookmarks${path}`, options, '书签操作失败')
}

export function initializeBookmarks(force = false) {
  if (pendingLoad) return pendingLoad
  if (initialized && !force) return Promise.resolve(true)
  bookmarksLoading.value = true
  bookmarksError.value = ''
  pendingLoad = (async () => {
    try {
      let version, result
      do {
        version = revision
        result = await api('?scope=all')
      } while (version !== revision)
      bookmarks.value = result
      initialized = true
      return true
    } catch (error) {
      bookmarksError.value = error.message
      return false
    } finally {
      bookmarksLoading.value = false
      pendingLoad = null
    }
  })()
  return pendingLoad
}

export function openBookmarkEditor(paperId, block, bookmark = null) {
  if (bookmarkSaving.value) return false
  bookmarkEditorError.value = ''
  bookmarksError.value = ''
  openPanel('toolbox')
  const existing = bookmark || bookmarkIndex.value.get(`${paperId}/${block.id}`)
  const text = block.text || block.caption || (
    block.type === 'equation' ? '论文公式' : block.asset ? '论文图表' : '论文片段')
  bookmarkEditor.value = { paperId, isNew: !existing, note: existing ? existing.note || existing.text : '',
    bookmark: existing || { id: 'draft-bookmark', isDraft: true, paper_id: paperId,
      paper_title: papers.value.find(paper => paper.id === paperId)?.title || '',
      block_id: block.id, page: block.page, bbox: block.bbox, text, note: '', pinned: false } }
  return true
}

export function closeBookmarkEditor() {
  if (!bookmarkSaving.value) bookmarkEditor.value = null
}

function replaceBookmark(bookmark) {
  ++revision
  bookmarks.value = [...bookmarks.value.filter(item => item.id !== bookmark.id), bookmark]
}

export async function saveBookmark(note) {
  const editor = bookmarkEditor.value
  if (!editor || bookmarkSaving.value) return false
  bookmarkSaving.value = true
  bookmarkEditorError.value = ''
  try {
    if (editor.isNew && !await initializeBookmarks()) throw new Error(bookmarksError.value)
    if (bookmarkEditor.value !== editor) return false
    const existing = editor.isNew ? bookmarkIndex.value.get(`${editor.paperId}/${editor.bookmark.block_id}`) : editor.bookmark
    const savedNote = note.trim() === editor.bookmark.text.trim() ? '' : note.trim()
    const result = await api(existing ? `/${editor.paperId}/${existing.id}` : '', {
      method: existing ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(existing ? { note: savedNote } : {
        paper_id: editor.paperId, block_id: editor.bookmark.block_id, note: savedNote,
      }),
    })
    if (bookmarkEditor.value === editor) {
      replaceBookmark(result)
      bookmarkEditor.value = null
      return true
    }
    return false
  } catch (error) {
    if (bookmarkEditor.value === editor) bookmarkEditorError.value = error.message
    return false
  } finally { bookmarkSaving.value = false }
}

async function withBookmarkAction(bookmark, operation) {
  if (bookmarkActions[bookmark.id]) return
  bookmarkActions[bookmark.id] = true
  bookmarksError.value = ''
  try { await operation() }
  catch (error) { bookmarksError.value = error.message }
  finally { delete bookmarkActions[bookmark.id] }
}

export function toggleBookmarkPinned(bookmark) {
  return withBookmarkAction(bookmark, async () => {
    replaceBookmark(await api(`/${bookmark.paper_id}/${bookmark.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !bookmark.pinned }),
    }))
  })
}

export function deleteBookmark(bookmark) {
  return withBookmarkAction(bookmark, async () => {
    await api(`/${bookmark.paper_id}/${bookmark.id}`, { method: 'DELETE' })
    ++revision
    bookmarks.value = bookmarks.value.filter(item => item.id !== bookmark.id)
    if (bookmarkEditor.value?.bookmark?.id === bookmark.id) bookmarkEditor.value = null
  })
}

watch(invalidatedPaper, event => {
  if (!event) return
  if (event.deleted) {
    ++revision
    bookmarks.value = bookmarks.value.filter(item => item.paper_id !== event.id)
  }
  if (bookmarkEditor.value?.paperId === event.id && (event.deleted || bookmarkEditor.value.isNew)) {
    bookmarkEditor.value = null
  }
})
