<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AppTopBar from './components/AppTopBar.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import DockColumn from './dock/DockColumn.vue'
import ResizeDivider from './dock/ResizeDivider.vue'
import { panels } from './dock/registry'
import { layout, panelColumn, resizingColumn } from './dock/useLayout'
import { activeId, importPapers, disposePapers } from './composables/usePapers.js'

const mounted = ref(false)
const settingsOpen = ref(false)
onMounted(() => { mounted.value = true })
onBeforeUnmount(disposePapers)
function panelActive(id) {
  const column = layout.columns[panelColumn(id)]
  return column && column.active === id && !column.collapsed
}
function dragFilesOver(event) {
  if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
}
function dropFiles(event) {
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  event.preventDefault()
  importPapers(files)
}
</script>

<template>
  <div class="app-shell" @dragover="dragFilesOver" @drop="dropFiles">
    <AppTopBar @open-settings="settingsOpen = true" />
    <SettingsDialog v-if="settingsOpen" @close="settingsOpen = false" />
    <main class="dock-area" :class="{ resizing: resizingColumn }">
      <DockColumn column="left" />
      <ResizeDivider column="left" />
      <DockColumn column="center" />
      <ResizeDivider column="right" />
      <DockColumn column="right" />
    </main>
    <template v-if="mounted">
      <!-- Original pages belong to one paper; keep only the current reader cached. -->
      <template v-for="(panel, id) in panels" :key="id">
        <Teleport v-if="panelColumn(id)" :to="`#dock-panel-${panelColumn(id)}`">
          <KeepAlive :max="1"><component :is="panel.component" v-if="panelActive(id)" :key="id === 'original' ? `${id}-${activeId}` : id" /></KeepAlive>
        </Teleport>
      </template>
    </template>
  </div>
</template>

<style scoped>
.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.dock-area {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 0;
  padding: 0 var(--dock-gap) var(--dock-gap);
}
.dock-area.resizing { user-select: none; cursor: col-resize; }
</style>
