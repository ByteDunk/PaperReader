<script setup>
import { computed, ref } from 'vue'
import { useContextMenu } from '../composables/useContextMenu.js'
import SearchInput from '../components/SearchInput.vue'
import AppBadge from '../components/AppBadge.vue'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import SegmentedControl from '../components/SegmentedControl.vue'
import { papers, activeId, selectPaper, importing, error, reading, paperActions, deletePaper, reparsePaper, retranslatePaper, reindexPaper } from '../composables/usePapers'
import { paperStatus, paperStatusDetails } from '../services/readerState'

const keyword = ref('')
const sort = ref('added')
const sortOptions = [
  { value: 'added', label: '导入时间' },
  { value: 'recent', label: '最近阅读' },
  { value: 'title', label: '标题' },
]
const { id: menuId, style: menuStyle, menu, toggle: toggleMenu, close: closeMenu, keydown: menuKeydown } = useContextMenu({
  selector: '.paper-menu, .paper-more', height: 160,
})
const menuPaper = computed(() => papers.value.find(p => p.id === menuId.value))
function runAction(action) {
  const id = menuId.value
  closeMenu(true)
  action(id)
}

const filtered = computed(previous => {
  const k = keyword.value.trim().toLowerCase()
  const result = papers.value.filter(
    p => p.title.toLowerCase().includes(k) || p.authors.toLowerCase().includes(k),
  )
  result.sort((a, b) => sort.value === 'title' ? a.title.localeCompare(b.title) :
    sort.value === 'recent' ? (reading[b.id]?.lastRead || 0) - (reading[a.id]?.lastRead || 0) :
      b.added_at.localeCompare(a.added_at))
  // A new lastRead timestamp usually leaves the order unchanged. Keep the
  // array stable so scrolling does not render the entire library every frame.
  return previous?.length === result.length && result.every((paper, i) => paper === previous[i]) ? previous : result
})
function progress(paper) {
  const position = reading[paper.id] || {}
  return Math.round(position.progress ?? ((position.page || 1) - 1) / paper.pages * 100)
}
</script>

<template>
  <div class="paper-list">
    <div class="list-head">
      <SearchInput v-model="keyword" placeholder="搜索标题 / 作者" />
      <div class="sort-row">
        <span class="count">共{{ filtered.length }}篇</span>
        <SegmentedControl v-model="sort" :options="sortOptions" class="sort-control" aria-label="论文显示顺序" />
      </div>
    </div>

    <ul class="list-body" @scroll="closeMenu()">
      <li v-if="!filtered.length">
        <EmptyState icon="library" :title="papers.length ? '没有匹配的论文' : '尚未导入论文'" hint="点击顶部“导入论文”，或将 PDF 拖入列表。" />
      </li>
      <li
        v-for="p in filtered"
        :key="p.id"
        class="paper-item"
        :class="{ active: p.id === activeId }"
        @click="selectPaper(p.id)"
      >
        <p class="paper-title">{{ p.title }}</p>
        <p class="paper-meta" :title="p.authors">{{ p.authors || p.filename }} · {{ p.pages }} 页</p>
        <div class="paper-foot">
          <progress class="paper-progress" :value="progress(p)" max="100" aria-label="阅读进度" />
          <span class="progress-num">{{ progress(p) }}%</span>
          <AppBadge :tone="paperStatus(p).tone" :title="paperStatusDetails(p)">{{ paperStatus(p).text }}</AppBadge>
          <button class="icon-btn paper-more" :title="`更多操作：${p.title}`" aria-haspopup="menu" :aria-expanded="menuId === p.id"
            :disabled="Boolean(paperActions[p.id])" @click.stop="toggleMenu($event, p.id)">
            <AppIcon :name="paperActions[p.id] ? 'loader' : 'more-horizontal'" :size="15" :class="{ spin: paperActions[p.id] }" />
          </button>
        </div>
      </li>
    </ul>

    <div class="drop-hint" :role="error ? 'alert' : 'status'">
      <AppIcon name="upload" :size="14" />
      {{ error || (importing ? '正在导入 PDF…' : '将 PDF 拖入此处导入') }}
    </div>
  </div>
  <Teleport to="body">
    <div v-if="menuPaper" ref="menu" class="paper-menu context-menu" :style="menuStyle" role="menu" aria-label="论文操作" @keydown="menuKeydown">
      <button role="menuitem" :disabled="menuPaper.state === 'parsing' || menuPaper.reparsing || Boolean(paperActions[menuPaper.id])" @click="runAction(reparsePaper)">
        <AppIcon name="rotate-cw" :size="14" />{{ menuPaper.state === 'parsing' || menuPaper.reparsing ? '正在重排…' : '重排论文' }}
      </button>
      <button role="menuitem" :disabled="menuPaper.state !== 'ready' || Boolean(paperActions[menuPaper.id])" @click="runAction(retranslatePaper)">
        <AppIcon name="languages" :size="14" />{{ menuPaper.translation?.state === 'waiting' ? '开始翻译' : '重新翻译' }}
      </button>
      <button role="menuitem" :disabled="menuPaper.state !== 'ready' || menuPaper.index?.state === 'indexing' || Boolean(paperActions[menuPaper.id])" @click="runAction(reindexPaper)">
        <AppIcon name="database" :size="14" />{{ menuPaper.index?.state === 'indexing' ? '正在索引…' : '重新索引' }}
      </button>
      <button role="menuitem" class="delete-action" :disabled="Boolean(paperActions[menuPaper.id])" @click="runAction(deletePaper)">
        <AppIcon name="trash" :size="14" />删除
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.paper-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.list-head {
  padding: 10px 10px 6px;
  flex: none;
}
.sort-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 2px 2px;
}
.count {
  flex: none;
  font-size: 11.5px;
  color: var(--text-3);
}
.sort-control { min-width: 0; margin-left: auto; }
.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: 4px 8px 8px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.paper-item {
  padding: 10px 12px;
  border-radius: var(--radius);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}
.paper-item:hover {
  background: var(--surface-2);
}
.paper-item.active {
  background: var(--surface-2);
  border-color: var(--border);
  box-shadow: inset 2.5px 0 0 var(--accent);
}
.paper-title {
  margin: 0 0 3px;
  font-size: 13px;
  font-weight: 550;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.paper-meta {
  margin: 0 0 8px;
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.paper-foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
.paper-progress {
  appearance: none;
  flex: 1;
  max-width: 72px;
  height: 4px;
  border: 0;
  border-radius: 99px;
  background: var(--surface-3);
  overflow: hidden;
}
.paper-progress::-webkit-progress-bar { background: var(--surface-3); }
.paper-progress::-webkit-progress-value { border-radius: inherit; background: var(--accent); transition: width .3s ease; }
.paper-progress::-moz-progress-bar { border-radius: inherit; background: var(--accent); }
.progress-num {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.paper-foot .badge {
  margin-left: auto;
}
.drop-hint {
  flex: none;
  margin: 0 10px 10px;
  padding: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-3);
  font-size: 12px;
}
</style>
