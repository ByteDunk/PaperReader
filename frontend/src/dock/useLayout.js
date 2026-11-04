import { reactive, ref, watch } from 'vue'

const STORAGE_KEY = 'paperreader.layout'

const defaultLayout = () => ({
  reflowTocWidth: null,
  columns: {
    left: { tabs: ['paper-list'], active: 'paper-list', collapsed: false, width: 258 },
    center: { tabs: ['original', 'reflow'], active: 'reflow', collapsed: false },
    right: { tabs: ['toolbox', 'translation', 'assistant'], active: 'translation', collapsed: false, width: 322 },
  },
})

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY))
    if (saved?.columns) {
      const restored = defaultLayout()
      if (Number.isFinite(saved.reflowTocWidth) && saved.reflowTocWidth > 0) restored.reflowTocWidth = saved.reflowTocWidth
      const knownTabs = Object.values(restored.columns).flatMap(c => c.tabs)
      const seen = new Set()
      for (const [column, state] of Object.entries(restored.columns)) {
        const stored = saved.columns[column]
        state.tabs = (Array.isArray(stored?.tabs) ? stored.tabs : []).filter(id => {
          if (!knownTabs.includes(id) || seen.has(id)) return false
          seen.add(id)
          return true
        })
        state.active = state.tabs.includes(stored?.active) ? stored.active : state.tabs[0] || ''
        state.collapsed = column !== 'center' && Boolean(stored?.collapsed)
        if (column !== 'center' && Number.isFinite(stored?.width)) state.width = Math.max(180, Math.min(620, stored.width))
      }
      for (const [column, state] of Object.entries(defaultLayout().columns)) {
        for (const id of state.tabs) {
          if (!seen.has(id)) restored.columns[column].tabs.push(id)
        }
        if (!restored.columns[column].active) restored.columns[column].active = restored.columns[column].tabs[0] || ''
      }
      return restored
    }
  } catch {
    /* 忽略损坏的持久化数据 */
  }
  return defaultLayout()
}

export const layout = reactive(load())
export const draggedTab = ref('')
export const dropTarget = ref(null)
export const resizingColumn = ref('')

watch(layout, v => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(v)) } catch { /* layout still works without storage */ }
}, { deep: true })

export function panelColumn(id) {
  return Object.keys(layout.columns).find(column => layout.columns[column].tabs.includes(id))
}

export function openPanel(id) {
  const column = panelColumn(id)
  if (column) activateTab(column, id)
}

let tutorialReturnTab = ''

export function openTutorial() {
  const center = layout.columns.center
  if (center.active !== 'tutorial') tutorialReturnTab = center.active
  const column = panelColumn('tutorial')
  if (column && column !== 'center') moveTab('tutorial', 'center')
  else if (!column) center.tabs.push('tutorial')
  activateTab('center', 'tutorial')
}

export function closeTutorial() {
  const column = panelColumn('tutorial')
  if (!column) return
  const state = layout.columns[column]
  const index = state.tabs.indexOf('tutorial')
  state.tabs.splice(index, 1)
  if (state.active === 'tutorial') {
    state.active = state.tabs.includes(tutorialReturnTab) ? tutorialReturnTab : state.tabs[Math.max(0, index - 1)] || ''
  }
}

export function moveTab(id, targetColumn, insertionIndex) {
  const sourceColumn = panelColumn(id)
  if (!sourceColumn || !layout.columns[targetColumn]) return
  const source = layout.columns[sourceColumn]
  const target = layout.columns[targetColumn]
  const oldIndex = source.tabs.indexOf(id)
  let index = insertionIndex ?? target.tabs.length
  source.tabs.splice(oldIndex, 1)
  if (sourceColumn === targetColumn && oldIndex < index) index--
  target.tabs.splice(Math.max(0, Math.min(index, target.tabs.length)), 0, id)
  if (sourceColumn !== targetColumn && source.active === id) {
    source.active = source.tabs[Math.min(oldIndex, source.tabs.length - 1)] || ''
  }
  activateTab(targetColumn, id)
}

export function finishTabDrag() {
  draggedTab.value = ''
  dropTarget.value = null
}

export function activateTab(column, id) {
  const col = layout.columns[column]
  col.active = id
  col.collapsed = false
}

export function toggleColumn(column) {
  const col = layout.columns[column]
  col.collapsed = !col.collapsed
}

export function resetLayout() {
  finishTabDrag()
  resizingColumn.value = ''
  Object.assign(layout, defaultLayout())
}
