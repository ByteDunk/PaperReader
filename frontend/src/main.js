import { createApp, nextTick, reactive } from 'vue'
import './styles/base.css'
import './styles/controls.css'
import './composables/useTheme'
import { initializeDesktop, showDesktopWindow, waitForDesktopModels } from './services/desktop.js'
import StartupView from './components/StartupView.vue'

async function start() {
  const root = document.querySelector('#app')
  const state = reactive({ phase: 'starting', error: '', groups: [] })
  const startup = createApp(StartupView, { state })
  startup.mount(root)
  try {
    await nextTick()
    // Resolve the maximized viewport's layout while the native window is hidden.
    root.getBoundingClientRect()
    await showDesktopWindow()
    let showTutorial = false
    await waitForDesktopModels(status => {
      if (['confirm', 'downloading', 'pausing', 'paused', 'download_error'].includes(status.phase)) showTutorial = true
      Object.assign(state, status)
    })
    await initializeDesktop()
    const { default: App } = await import('./App.vue')
    if (showTutorial) {
      const { openTutorial } = await import('./dock/useLayout.js')
      openTutorial()
    }
    startup.unmount()
    createApp(App).mount(root)
  } catch (error) {
    state.error = `应用启动失败，请关闭后重新打开。\n${error?.message || error}`
    await nextTick()
    // Backend startup failures must remain visible, with working window controls.
    await showDesktopWindow().catch(error => console.error('无法显示启动错误。', error))
  }
}

start()
