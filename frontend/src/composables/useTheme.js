import { computed, ref, watchEffect } from 'vue'

const STORAGE_KEY = 'paperreader.theme'

const systemTheme = matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(systemTheme.matches)
let saved
try { saved = localStorage.getItem(STORAGE_KEY) } catch {}

export const themeMode = ref(['light', 'dark', 'system'].includes(saved) ? saved : 'system')
export const theme = computed(() => themeMode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : themeMode.value)

function syncSystemTheme(event) { systemDark.value = event.matches }
systemTheme.addEventListener('change', syncSystemTheme)
if (import.meta.hot) import.meta.hot.dispose(() => systemTheme.removeEventListener('change', syncSystemTheme))

watchEffect(() => {
  document.documentElement.dataset.theme = theme.value
  try { localStorage.setItem(STORAGE_KEY, themeMode.value) } catch {}
})

export function toggleTheme() {
  themeMode.value = theme.value === 'dark' ? 'light' : 'dark'
}
