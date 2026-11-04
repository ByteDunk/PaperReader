<script setup>
import { computed } from 'vue'
import { panels } from './registry'
import { layout, activateTab, toggleColumn, moveTab, draggedTab, dropTarget, finishTabDrag, resizingColumn } from './useLayout'
import AppIcon from '../components/AppIcon.vue'
import IconButton from '../components/IconButton.vue'

const props = defineProps({
  column: { type: String, required: true }, // left | center | right
})

const state = computed(() => layout.columns[props.column])
const collapsible = computed(() => props.column !== 'center')
const isDropTarget = computed(() => dropTarget.value?.column === props.column)

function startDrag(event, id) {
  draggedTab.value = id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-paperreader-tab', id)
}
function dragOver(event) {
  if (!draggedTab.value) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  const tab = event.target.closest('[data-tab]')
  let index = state.value.tabs.length
  if (tab) {
    const rect = tab.getBoundingClientRect()
    const after = state.value.collapsed ? event.clientY > rect.top + rect.height / 2 : event.clientX > rect.left + rect.width / 2
    index = state.value.tabs.indexOf(tab.dataset.tab) + (after ? 1 : 0)
  }
  dropTarget.value = { column: props.column, index }
}
function drop(event) {
  if (!draggedTab.value) return
  event.preventDefault()
  moveTab(draggedTab.value, props.column, isDropTarget.value ? dropTarget.value.index : state.value.tabs.length)
  finishTabDrag()
}
function dragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget) && isDropTarget.value) dropTarget.value = null
}
const foldIcon = computed(() =>
  props.column === 'left'
    ? state.value.collapsed
      ? 'chevrons-right'
      : 'chevrons-left'
    : state.value.collapsed
      ? 'chevrons-left'
      : 'chevrons-right',
)
</script>

<template>
  <section class="dock-column" :data-column="column"
    :class="[`dock-${column}`, { collapsed: state.collapsed, 'drop-target': isDropTarget, resizing: resizingColumn }]"
    :style="collapsible && !state.collapsed ? { width: `${state.width}px` } : null"
    @dragover="dragOver" @drop="drop" @dragleave="dragLeave">
      <header v-show="!state.collapsed" class="tab-bar">
        <button
          v-for="id in state.tabs"
          :key="id"
          class="tab"
          :class="{ active: id === state.active, 'drop-before': isDropTarget && dropTarget.index === state.tabs.indexOf(id) }"
          :data-tab="id" draggable="true" @dragstart="startDrag($event, id)" @dragend="finishTabDrag"
          @click="activateTab(column, id)"
        >
          <AppIcon :name="panels[id].icon" :size="13.5" />
          <span>{{ panels[id].title }}</span>
        </button>
        <span class="spacer" />
        <IconButton
          v-if="collapsible"
          :icon="foldIcon"
          title="收起栏"
          :size="13"
          @click="toggleColumn(column)"
        />
      </header>
      <div :id="`dock-panel-${column}`" v-show="!state.collapsed" class="panel-body" />
      <p v-if="!state.collapsed && !state.tabs.length" class="empty-panel">将标签页拖入此处</p>

    <div v-show="state.collapsed" class="collapsed-strip">
      <IconButton :icon="foldIcon" title="展开栏" :size="13" @click="toggleColumn(column)" />
      <span class="strip-divider" />
      <button
        v-for="id in state.tabs"
        :key="id"
        class="strip-tab"
        :title="panels[id].title"
        :data-tab="id" draggable="true" @dragstart="startDrag($event, id)" @dragend="finishTabDrag"
        @click="activateTab(column, id)"
      >
        <AppIcon :name="panels[id].icon" :size="15" />
      </button>
    </div>
  </section>
</template>

<style scoped>
.dock-column {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-l);
  overflow: hidden;
  transition: width 0.2s ease;
}
.dock-left,
.dock-right {
  flex: none;
}
.dock-center {
  flex: 1;
  min-width: 0;
}
.dock-column.collapsed {
  width: 44px;
}
.dock-column.resizing { transition: none; }
.dock-column.drop-target { border-color: var(--accent); }
.empty-panel { position: absolute; left: 0; right: 0; top: 50%; margin: 0; padding: 16px; text-align: center; font-size: 12px; color: var(--text-3); pointer-events: none; }

.tab-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  flex: none;
  overflow-x: auto;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: var(--control-height);
  padding: 0 10px;
  border-radius: var(--radius-s);
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease;
  flex: none;
  position: relative;
}
.tab.drop-before::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 3px;
  bottom: 3px;
  width: 2px;
  background: var(--accent);
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  background: var(--surface-3);
  color: var(--text);
  font-weight: 600;
}
.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.collapsed-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 0;
}
.strip-divider {
  width: 20px;
  height: 1px;
  background: var(--border);
  margin: 3px 0;
}
.strip-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--control-height);
  height: var(--control-height);
  border-radius: var(--radius-s);
  color: var(--text-2);
  transition: background-color 0.15s ease, color 0.15s ease;
}
.strip-tab:hover {
  background: var(--surface-3);
  color: var(--text);
}
</style>
