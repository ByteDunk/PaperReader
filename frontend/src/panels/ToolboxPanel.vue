<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useContextMenu } from '../composables/useContextMenu.js'
import CollapseSection from '../components/CollapseSection.vue'
import SearchInput from '../components/SearchInput.vue'
import SegmentedControl from '../components/SegmentedControl.vue'
import AppBadge from '../components/AppBadge.vue'
import AppIcon from '../components/AppIcon.vue'
import { activeId, activePaper, locateSource, selectPaper, invalidatedPaper } from '../composables/usePapers'
import { requestJson } from '../services/http.js'
import { bookmarks, bookmarkIndex, bookmarksLoading, bookmarksError, bookmarkActions, bookmarkEditor, bookmarkEditorError, bookmarkSaving, initializeBookmarks, openBookmarkEditor, closeBookmarkEditor, saveBookmark, toggleBookmarkPinned, deleteBookmark } from '../composables/useBookmarks.js'

const query = ref('')
const scope = ref('paper')
const scopeOptions = [
  { value: 'paper', label: '当前论文' },
  { value: 'all', label: '全库' },
]

const results = ref([])
const searching = ref(false)
const searched = ref(false)
const searchError = ref('')
const pendingPapers = ref(0)
const resultScope = ref('paper')
const canSearch = computed(() => query.value.trim() && !searching.value && (scope.value === 'all' || activeId.value))
let controller = null
let requestVersion = 0

function resetSearch() {
  ++requestVersion
  controller?.abort()
  searching.value = false
  searched.value = false
  results.value = []
  searchError.value = ''
  pendingPapers.value = 0
}
watch([scope, activeId, query, invalidatedPaper], resetSearch)
onBeforeUnmount(resetSearch)

async function search() {
  if (!canSearch.value) return
  controller?.abort()
  controller = new AbortController()
  const version = ++requestVersion
  searching.value = true
  searchError.value = ''
  results.value = []
  pendingPapers.value = 0
  searched.value = false
  try {
    const response = await requestJson('/api/search', {
      method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query.value.trim(), scope: scope.value, paper_id: scope.value === 'paper' ? activeId.value : null }),
    }, '搜索失败')
    if (version !== requestVersion) return
    results.value = response.results
    resultScope.value = response.scope
    pendingPapers.value = response.pending_papers
    searched.value = true
  } catch (error) {
    if (version === requestVersion && error.name !== 'AbortError') searchError.value = error.message
  } finally {
    if (version === requestVersion) searching.value = false
  }
}

async function openResult(result) {
  searchError.value = ''
  if (activeId.value !== result.paper_id) await selectPaper(result.paper_id)
  if (activeId.value === result.paper_id) locateSource(result)
}

const bookmarkScope = ref('paper')
const bookmarkSection = ref(null)
const bookmarkDraft = ref('')
const editingBookmarkId = computed(() => bookmarkEditor.value?.bookmark?.id || '')
const visibleBookmarks = computed(() => {
  const result = bookmarks.value
    .filter(item => bookmarkScope.value === 'all' || item.paper_id === activeId.value)
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
  const editor = bookmarkEditor.value
  if (editor?.isNew && (bookmarkScope.value === 'all' || editor.paperId === activeId.value)) result.unshift(editor.bookmark)
  return result
})
const { id: bookmarkMenuId, style: bookmarkMenuStyle, menu: bookmarkMenu,
  toggle: toggleBookmarkMenu, close: closeBookmarkMenu, keydown: bookmarkMenuKeydown } = useContextMenu({
  selector: '.bookmark-menu, .bookmark-more', height: 112,
})
const menuBookmark = computed(() => visibleBookmarks.value.find(item => item.id === bookmarkMenuId.value))
const bookmarkNavigationError = ref('')
function runBookmarkAction(action) {
  const bookmark = menuBookmark.value
  closeBookmarkMenu(true)
  if (bookmark) action(bookmark)
}
function editBookmark(bookmark) {
  openBookmarkEditor(bookmark.paper_id, { id: bookmark.block_id, text: bookmark.text }, bookmark)
}
async function focusBookmarkEditor() {
  const id = editingBookmarkId.value
  if (!id) return
  if (bookmarkScope.value === 'paper' && bookmarkEditor.value.paperId !== activeId.value) bookmarkScope.value = 'all'
  await nextTick()
  bookmarkSection.value?.expand()
  await nextTick()
  if (editingBookmarkId.value !== id) return
  const item = bookmarkSection.value?.$el.querySelector(`[data-bookmark-id="${id}"]`)
  const input = item?.querySelector('.bookmark-note-input')
  input?.focus({ preventScroll: true })
  if (!bookmarkEditor.value.isNew) input?.select()
  item?.scrollIntoView({ block: bookmarkEditor.value.isNew ? 'start' : 'nearest' })
}
async function focusBookmarkItem(id) {
  await nextTick()
  bookmarkSection.value?.$el.querySelector(`[data-bookmark-id="${id}"] .bookmark-content`)?.focus({ preventScroll: true })
}
function cancelBookmarkNote() {
  const id = editingBookmarkId.value
  closeBookmarkEditor()
  if (!editingBookmarkId.value) focusBookmarkItem(id)
}
async function saveBookmarkNote() {
  const editor = bookmarkEditor.value
  if (editor && await saveBookmark(bookmarkDraft.value)) {
    const id = bookmarkIndex.value.get(`${editor.paperId}/${editor.bookmark.block_id}`)?.id
    if (id) focusBookmarkItem(id)
  }
}
watch(bookmarkEditor, editor => {
  if (!editor?.bookmark) return
  bookmarkDraft.value = editor.note
  focusBookmarkEditor()
}, { immediate: true, flush: 'post' })
onActivated(focusBookmarkEditor)
async function openBookmark(bookmark) {
  bookmarkNavigationError.value = ''
  if (activeId.value !== bookmark.paper_id) await selectPaper(bookmark.paper_id)
  if (activeId.value === bookmark.paper_id) locateSource(bookmark)
  else bookmarkNavigationError.value = '论文暂时无法打开，请稍后重试。'
}
watch([bookmarkScope, activeId, invalidatedPaper], () => { closeBookmarkMenu(); bookmarkNavigationError.value = '' })
onMounted(() => initializeBookmarks())
</script>

<template>
  <div class="toolbox" @scroll="closeBookmarkMenu()">
    <CollapseSection title="搜索" icon="search" default-open>
      <div class="section-stack">
        <SearchInput v-model="query" placeholder="输入关键词或问题…" />
        <div class="row">
          <span class="row-label">范围</span>
          <span class="spacer" />
          <SegmentedControl v-model="scope" :options="scopeOptions" />
          <button type="button" class="ui-button ui-button--primary ui-button--compact" :disabled="!canSearch" @click="search">
            <AppIcon name="search" :size="13" />{{ searching ? '搜索中…' : '搜索' }}
          </button>
        </div>
        <p v-if="searchError" class="search-message error" role="alert">{{ searchError }}</p>
        <p v-else-if="searching" class="search-message" role="status">正在检索相关片段…</p>
        <p v-else-if="searched && !results.length" class="search-message">未找到相关片段。</p>
        <p v-else-if="!searched" class="search-message">{{ scope === 'paper' && !activePaper ? '请先导入或选择论文。' : '输入关键词或问题，点击搜索查找相关原文。' }}</p>
        <p class="search-message">搜索同时支持字符串匹配和语义检索。</p>
        <p v-if="pendingPapers" class="search-message">还有 {{ pendingPapers }} 篇论文索引未就绪，本次搜索已完成的索引。</p>
        <ul class="result-list">
          <li v-for="r in results" :key="r.id" class="result-item" tabindex="0" role="button" :aria-label="`查看第 ${r.page} 页来源`" @click="openResult(r)" @keydown.enter.prevent="openResult(r)" @keydown.space.prevent="openResult(r)">
            <p class="result-text">{{ r.text }}</p>
            <div class="result-meta">
              <div class="result-source">
                <AppBadge>第 {{ r.page }} 页</AppBadge>
                <AppBadge v-if="resultScope === 'all'" class="paper-title" :title="r.paper_title">{{ r.paper_title }}</AppBadge>
              </div>
              <span v-if="r.similarity !== null" class="score" title="匹配度（字符串匹配为 1.0，其余为语义相似度）">{{ r.similarity.toFixed(2) }}</span>
            </div>
          </li>
        </ul>
      </div>
    </CollapseSection>

    <CollapseSection ref="bookmarkSection" title="书签" icon="bookmark" default-open @click="closeBookmarkMenu()">
      <div class="section-stack">
        <div class="row">
          <span class="row-label">范围</span>
          <span class="spacer" />
          <SegmentedControl v-model="bookmarkScope" :options="scopeOptions" />
        </div>
        <p v-if="bookmarksError || bookmarkNavigationError" class="search-message error" role="alert">
          {{ bookmarksError || bookmarkNavigationError }}
          <button v-if="bookmarksError" type="button" class="bookmark-retry" @click="initializeBookmarks(true)">重试</button>
        </p>
        <p v-else-if="bookmarksLoading" class="search-message" role="status">正在加载书签…</p>
        <p v-else-if="!visibleBookmarks.length" class="search-message">{{ bookmarkScope === 'paper' && !activePaper ? '请先导入或选择论文。' : '暂无书签，点击重排段落右下角的书签按钮添加。' }}</p>
        <ul class="result-list">
          <li v-for="bookmark in visibleBookmarks" :key="bookmark.id" class="result-item bookmark-item" :data-bookmark-id="bookmark.id">
            <form v-if="editingBookmarkId === bookmark.id" class="bookmark-note-editor" @submit.prevent="saveBookmarkNote" @keydown.esc.stop.prevent="cancelBookmarkNote" @keydown.ctrl.enter.prevent="saveBookmarkNote" @keydown.meta.enter.prevent="saveBookmarkNote">
              <textarea v-model="bookmarkDraft" class="ui-textarea bookmark-note-input" aria-label="书签备注" rows="3" maxlength="2000" placeholder="输入备注内容" :disabled="bookmarkSaving" />
              <p v-if="bookmarkEditorError" class="search-message error" role="alert">{{ bookmarkEditorError }}</p>
              <div class="bookmark-edit-actions">
                <button type="button" class="ui-button ui-button--compact" :disabled="bookmarkSaving" @click="cancelBookmarkNote">取消</button>
                <button type="submit" class="ui-button ui-button--primary ui-button--compact" :disabled="bookmarkSaving">{{ bookmarkSaving ? '保存中…' : '保存' }}</button>
              </div>
            </form>
            <button type="button" class="bookmark-content" :aria-label="`查看书签：${bookmark.note || bookmark.text}`" @click="openBookmark(bookmark)">
              <p v-if="editingBookmarkId !== bookmark.id" class="bookmark-note" :title="bookmark.note || bookmark.text">{{ bookmark.note || bookmark.text }}</p>
              <p class="bookmark-text" :title="bookmark.text">{{ bookmark.text }}</p>
            </button>
            <div class="result-meta">
              <button type="button" class="result-source bookmark-source" :aria-label="`查看第 ${bookmark.page} 页来源`" @click="openBookmark(bookmark)">
                <AppBadge>第 {{ bookmark.page }} 页</AppBadge>
                <AppBadge v-if="bookmarkScope === 'all'" class="paper-title" :title="bookmark.paper_title">{{ bookmark.paper_title }}</AppBadge>
              </button>
              <AppIcon v-if="bookmark.pinned" name="pin" :size="12" class="bookmark-pinned" title="已置顶" />
              <button v-if="!bookmark.isDraft" type="button" class="icon-btn bookmark-more" title="书签操作" aria-label="书签操作" aria-haspopup="menu"
                :aria-expanded="bookmarkMenuId === bookmark.id" :disabled="Boolean(bookmarkActions[bookmark.id]) || (bookmarkSaving && editingBookmarkId === bookmark.id)"
                @click.stop="toggleBookmarkMenu($event, bookmark.id)">
                <AppIcon :name="bookmarkActions[bookmark.id] ? 'loader' : 'more-horizontal'" :size="15" :class="{ spin: bookmarkActions[bookmark.id] }" />
              </button>
            </div>
          </li>
        </ul>
      </div>
    </CollapseSection>
  </div>
  <Teleport to="body">
    <div v-if="menuBookmark" ref="bookmarkMenu" class="bookmark-menu context-menu" :style="bookmarkMenuStyle" role="menu" aria-label="书签操作" @keydown="bookmarkMenuKeydown">
      <button type="button" role="menuitem" :disabled="Boolean(bookmarkActions[menuBookmark.id])" @click="runBookmarkAction(editBookmark)">
        <AppIcon name="pencil" :size="14" />编辑备注
      </button>
      <button type="button" role="menuitem" :disabled="Boolean(bookmarkActions[menuBookmark.id])" @click="runBookmarkAction(toggleBookmarkPinned)">
        <AppIcon name="pin" :size="14" />{{ menuBookmark.pinned ? '取消置顶' : '置顶' }}
      </button>
      <button type="button" role="menuitem" class="delete-action" :disabled="Boolean(bookmarkActions[menuBookmark.id])" @click="runBookmarkAction(deleteBookmark)">
        <AppIcon name="trash" :size="14" />删除
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.toolbox {
  flex: 1;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overscroll-behavior: contain;
}
.toolbox > :deep(.collapse) { flex-shrink: 0; }
.section-stack {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding-top: 6px;
}
.row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0;
}
.row-label {
  flex: none;
  white-space: nowrap;
  font-size: 12.5px;
  color: var(--text-2);
}
.row > .ui-button { margin-left: auto; }
.result-list {
  list-style: none;
  margin: 2px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.result-item {
  padding: 9px 11px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.result-item:hover {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
.result-text {
  margin: 0 0 7px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.result-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.result-source { display: flex; align-items: center; gap: 5px; min-width: 0; flex: 1; }
.paper-title { display: block; min-width: 0; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.search-message { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-3); }
.search-message.error { color: var(--danger); }
.score {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  margin-left: 7px;
}
.bookmark-item { scroll-margin-top: 10px; }
.bookmark-content { display: block; width: 100%; text-align: left; }
.bookmark-note {
  margin: 0 0 4px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text);
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
}
.bookmark-text { margin: 0 0 7px; color: var(--text-3); font-size: 12px; line-height: 1.6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bookmark-note-editor { display: flex; flex-direction: column; gap: 7px; margin-bottom: 7px; }
.bookmark-note-input { display: block; width: 100%; min-height: 72px; resize: vertical; font-size: 12.5px; }
.bookmark-edit-actions { display: flex; justify-content: flex-end; gap: 6px; }
.bookmark-source { text-align: left; overflow: hidden; }
.bookmark-source .badge { flex-shrink: 0; }
.bookmark-source .paper-title { flex-shrink: 1; }
.bookmark-pinned { flex: none; margin-left: 5px; color: var(--accent); }
.bookmark-more { margin-left: 5px; }
.bookmark-retry { margin-left: 5px; color: var(--accent); font-size: inherit; }
</style>
