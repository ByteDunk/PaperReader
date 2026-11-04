<script setup>
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import IconButton from './IconButton.vue'
import { theme, toggleTheme } from '../composables/useTheme'
import { openTutorial, resetLayout } from '../dock/useLayout'
import { importPapers, importing, initializePapers } from '../composables/usePapers'
import { useDesktopWindow } from '../composables/useDesktopWindow'

const fileInput = ref(null)
const props = defineProps({ ready: { type: Boolean, default: true } })
const { desktop, maximized, changingMaximized, windowError, minimize, toggleMaximized, close } = useDesktopWindow()
defineEmits(['open-settings'])
onMounted(() => { if (props.ready) initializePapers() })
async function chooseFiles(event) {
  await importPapers(Array.from(event.target.files || []))
  event.target.value = ''
}
</script>

<template>
  <header class="top-bar" :class="{ 'desktop-bar': desktop }" :data-tauri-drag-region="desktop ? '' : undefined">
    <div class="brand" :data-tauri-drag-region="desktop ? '' : undefined">
      <span class="brand-logo"><img src="/app-icon.png" alt="" width="36" height="36" /></span>
      <span class="brand-name">论文阅读器</span>
    </div>

    <input ref="fileInput" type="file" accept=".pdf,application/pdf" multiple hidden @change="chooseFiles" />
    <button class="ui-button ui-button--primary import-btn" title="导入 PDF 论文" :disabled="!ready || importing" @click="fileInput.click()">
      <AppIcon name="upload" :size="14" />
      {{ importing ? '正在导入…' : '导入论文' }}
    </button>

    <span class="spacer" :data-tauri-drag-region="desktop ? '' : undefined" />

    <IconButton class="toolbar-action" icon="book-open" :size="16" title="使用教程" aria-label="使用教程" :disabled="!ready" @click="openTutorial" />
    <IconButton class="toolbar-action" icon="layout" :size="16" title="重置默认布局" :disabled="!ready" @click="resetLayout" />
    <IconButton
      class="toolbar-action"
      :size="16"
      :icon="theme === 'dark' ? 'sun' : 'moon'"
      :title="theme === 'dark' ? '切换为亮色模式' : '切换为暗色模式'"
      :disabled="!ready"
      @click="toggleTheme"
    />
    <IconButton class="toolbar-action" icon="settings" :size="16" title="设置" aria-label="设置" aria-haspopup="dialog" :disabled="!ready" @click="$emit('open-settings')" />

    <template v-if="desktop">
      <span class="divider" aria-hidden="true" />
      <div class="window-controls" role="group" aria-label="窗口控制">
        <button type="button" class="window-btn" title="最小化" aria-label="最小化" @click="minimize">
          <AppIcon name="minimize" :size="15" />
        </button>
        <button
          type="button" class="window-btn"
          :title="maximized ? '还原窗口' : '最大化'"
          :aria-label="maximized ? '还原窗口' : '最大化'" :aria-pressed="maximized"
          :disabled="changingMaximized" @click="toggleMaximized"
        >
          <AppIcon :name="maximized ? 'window-restore' : 'window-maximize'" :size="15" />
        </button>
        <button type="button" class="window-btn window-close" title="关闭" aria-label="关闭" @click="close">
          <AppIcon name="x" :size="17" />
        </button>
      </div>
      <p v-if="windowError" class="window-error" role="alert">{{ windowError }}</p>
    </template>
  </header>
</template>

<style scoped>
.top-bar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 48px;
  padding: 0 6px;
  flex: none;
}
.desktop-bar {
  padding-right: 0;
  user-select: none;
}
.top-bar > .spacer {
  align-self: stretch;
  min-width: 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
  margin-right: 12px;
}
.desktop-bar .brand > * {
  pointer-events: none;
}
.brand-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex: none;
  border-radius: 8px;
  overflow: hidden;
  background: transparent;
}
.brand-logo img {
  display: block;
  width: 40px;
  height: 40px;
  object-fit: contain;
}
.brand-name {
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: 0.2px;
}
.import-btn {
  border: 0;
  font-size: 13px;
  font-weight: 550;
}
.toolbar-action {
  --icon-button-size: 30px;
}
.divider {
  width: 1px;
  height: 20px;
  background: var(--border-strong);
  margin: 0 2px;
  flex: none;
}
.window-controls {
  display: flex;
  align-self: stretch;
  align-items: stretch;
  flex: none;
}
.window-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  border-radius: 0;
  color: var(--text-2);
  transition: background-color 0.15s ease, color 0.15s ease;
}
.window-btn:hover:not(:disabled) {
  background: var(--surface-3);
  color: var(--text);
}
.window-btn:focus-visible {
  outline-offset: -4px;
}
.window-btn.window-close:hover:not(:disabled) {
  background: #c42b1c;
  color: #fff;
}
.window-error {
  position: absolute;
  top: 100%;
  right: 10px;
  z-index: 10;
  margin: 0;
  padding: 8px 12px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-s);
  background: var(--surface);
  color: var(--danger);
  box-shadow: var(--shadow-sm);
}
</style>
