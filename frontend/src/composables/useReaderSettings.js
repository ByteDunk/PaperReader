import { reactive, watch } from 'vue'

const storageKey = 'paper-reader-display'
const defaults = { titleFontSize: 20, fontSize: 14, lineHeight: 18, showPageAnchors: true }
let saved = {}
try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {} } catch {}

export const readerSettings = reactive({
  titleFontSize: Number.isInteger(saved.titleFontSize) && saved.titleFontSize >= 16 && saved.titleFontSize <= 30 ? saved.titleFontSize : defaults.titleFontSize,
  fontSize: Number.isInteger(saved.fontSize) && saved.fontSize >= 12 && saved.fontSize <= 18 ? saved.fontSize : defaults.fontSize,
  lineHeight: Number.isInteger(saved.lineHeight) && saved.lineHeight >= 15 && saved.lineHeight <= 22 ? saved.lineHeight : defaults.lineHeight,
  showPageAnchors: typeof saved.showPageAnchors === 'boolean' ? saved.showPageAnchors : defaults.showPageAnchors,
})

watch(readerSettings, value => {
  try { localStorage.setItem(storageKey, JSON.stringify(value)) } catch {}
})
