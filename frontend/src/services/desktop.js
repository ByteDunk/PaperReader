import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

let connection = null

export async function showDesktopWindow() {
  if (!window.__TAURI_INTERNALS__) return
  // Give the mounted startup screen a rendering opportunity before revealing
  // the native window. Hidden WebViews can suspend animation frames, so bound
  // the wait and cancel any frame left pending when the timer wins.
  await new Promise(resolve => {
    let frame
    const finish = () => {
      clearTimeout(timer)
      cancelAnimationFrame(frame)
      resolve()
    }
    const timer = setTimeout(finish, 100)
    frame = requestAnimationFrame(() => { frame = requestAnimationFrame(finish) })
  })
  await invoke('desktop_frontend_ready')
}

export async function initializeDesktop() {
  if (window.__TAURI_INTERNALS__) {
    connection = await invoke('desktop_connection')
  }
}

export async function waitForDesktopModels(onStatus) {
  if (!window.__TAURI_INTERNALS__) return
  for (;;) {
    const status = await invoke('desktop_startup_status')
    onStatus(status)
    if (status.phase === 'ready') return
    if (status.phase === 'error') throw new Error(status.error)
    await new Promise(resolve => setTimeout(resolve, 250))
  }
}

export async function downloadDesktopModels(pause = false) {
  await invoke('desktop_download_models', { pause })
}

export async function closeDesktopApp() {
  await getCurrentWindow().close()
}

export function apiUrl(path, resource = false) {
  if (!connection) return path
  if (!path.startsWith('/api/')) throw new Error('无效的应用资源地址。')
  const url = new URL(path, connection.baseUrl)
  if (resource) url.searchParams.set('desktop_token', connection.token)
  return url.href
}

export function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers)
  if (connection) headers.set('X-PaperReader-Token', connection.token)
  return fetch(apiUrl(path), { ...options, headers })
}
