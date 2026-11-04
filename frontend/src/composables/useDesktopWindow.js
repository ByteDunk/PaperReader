import { onMounted, onUnmounted, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

export function useDesktopWindow() {
  const desktop = isTauri()
  const appWindow = desktop ? getCurrentWindow() : null
  const maximized = ref(desktop)
  const changingMaximized = ref(false)
  const windowError = ref('')
  let disposed = false
  let unlistenResize

  async function run(action, message) {
    windowError.value = ''
    try { await action() }
    catch (error) {
      windowError.value = message
      console.error(message, error)
    }
  }

  async function syncMaximized() {
    const value = await appWindow.isMaximized()
    if (!disposed) maximized.value = value
  }

  async function toggleMaximized() {
    if (!appWindow || changingMaximized.value) return
    changingMaximized.value = true
    try {
      await run(async () => {
        await appWindow.toggleMaximize()
        await syncMaximized()
      }, '无法调整窗口大小，请重试。')
    } finally { changingMaximized.value = false }
  }

  function minimize() {
    if (appWindow) return run(() => appWindow.minimize(), '无法最小化窗口，请重试。')
  }

  function close() {
    // Request the normal native close path so the host also stops its backend.
    if (appWindow) return run(() => appWindow.close(), '无法关闭窗口，请重试。')
  }

  onMounted(async () => {
    if (!appWindow) return
    await run(async () => {
      const unlisten = await appWindow.onResized(() => {
        void run(syncMaximized, '无法读取窗口状态，请重试。')
      })
      if (disposed) { unlisten(); return }
      unlistenResize = unlisten
      await syncMaximized()
    }, '无法读取窗口状态，请重试。')
  })

  onUnmounted(() => {
    disposed = true
    unlistenResize?.()
  })

  return { desktop, maximized, changingMaximized, windowError, minimize, toggleMaximized, close }
}
