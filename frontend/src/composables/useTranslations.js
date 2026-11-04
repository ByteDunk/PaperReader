import { computed, ref, shallowRef, watch } from 'vue'
import { layout, panelColumn } from '../dock/useLayout.js'
import { activeId, activePaper, reading, invalidatedPaper, reflowScrolling } from './usePapers.js'
import { paperApi as api } from '../services/http.js'

export const translation = shallowRef(null)
export const translationLoading = ref(false)
export const translationError = ref('')
export const translationPage = computed(() => Math.max(1, Math.min(activePaper.value?.pages || 1,
  reading[activeId.value]?.reflowPage || 1)))
export const translationPageProgress = computed(() => Math.max(0, Math.min(1,
  Number(reading[activeId.value]?.reflowPageProgress) || 0)))
export const translationForeground = computed(() => {
  const column = layout.columns[panelColumn('translation')]
  return column?.active === 'translation' && !column.collapsed
})
let initialized = false
let timer, controller, stopWatch, stopInvalidation, stopScrollWatch, stopDeferralWatch
let version = 0
let refreshPending = false
const scrollOrigin = shallowRef(null)
const deferRefresh = computed(() => reflowScrolling.value && scrollOrigin.value?.paperId === activeId.value
  && Math.abs(translationPage.value - scrollOrigin.value.page) > 1)

function cancel() {
  ++version
  clearTimeout(timer)
  controller?.abort()
  controller = null
  refreshPending = false
  translationLoading.value = false
}

export async function refreshTranslation() {
  cancel()
  if (!translationForeground.value || !activeId.value || activePaper.value?.state === 'unparsed') return
  // Adjacent pages update immediately. A burst spanning multiple pages waits
  // for scrolling to settle, avoiding intermediate rich-text rebuilds.
  if (deferRefresh.value) {
    refreshPending = true
    return
  }
  const current = version
  const id = activeId.value, page = translationPage.value
  controller = new AbortController()
  translationLoading.value = !translation.value
  try {
    const result = await api(`/${id}/translation?page=${page}`, { signal: controller.signal, cache: 'no-store' })
    if (current !== version) return
    const value = { ...result, paperId: id, page }
    if (JSON.stringify(translation.value) !== JSON.stringify(value)) translation.value = value
    translationError.value = ''
  } catch (e) {
    if (current === version && e.name !== 'AbortError') translationError.value = e.message
  } finally {
    if (current === version) {
      translationLoading.value = false
      controller = null
      if (translationForeground.value) {
        timer = setTimeout(refreshTranslation, translation.value?.state === 'translating' ? 700 : 2500)
      }
    }
  }
}

export function initializeTranslations() {
  if (initialized) return
  initialized = true
  stopScrollWatch = watch(reflowScrolling, scrolling => {
    scrollOrigin.value = scrolling ? { paperId: activeId.value, page: translationPage.value } : null
  }, { flush: 'sync', immediate: true })
  stopDeferralWatch = watch(deferRefresh, deferred => {
    if (deferred && controller) {
      cancel()
      refreshPending = true
    } else if (!deferred && refreshPending) refreshTranslation()
  }, { flush: 'sync' })
  stopInvalidation = watch(invalidatedPaper, event => {
    if (translation.value?.paperId === event?.id || activeId.value === event?.id) {
      cancel()
      translation.value = null
      translationError.value = ''
      if (!event.deleted && !event.cleared) refreshTranslation()
    }
  }, { flush: 'sync' })
  stopWatch = watch([activeId, translationPage, translationForeground, () => activePaper.value?.state, () => activePaper.value?.translation?.revision], () => {
    // Keep the displayed page intact until its replacement arrives. Clearing
    // it at every boundary causes two DOM rebuilds and a loading flash.
    if (translation.value?.paperId !== activeId.value || activePaper.value?.state === 'unparsed') {
      translation.value = null
    }
    if (translation.value?.paperId !== activeId.value || translation.value?.page !== translationPage.value) {
      translationError.value = ''
    }
    refreshTranslation()
  }, { immediate: true })
}

export function disposeTranslations() {
  cancel()
  stopWatch?.()
  stopInvalidation?.()
  stopScrollWatch?.()
  stopDeferralWatch?.()
  scrollOrigin.value = null
  translation.value = null
  initialized = false
}
