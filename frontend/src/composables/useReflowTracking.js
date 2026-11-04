import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, watch } from 'vue'
import { indexReflowBlocks, readReflowPosition } from '../services/reflowGeometry.js'
import { activeId, document as paperDocument, loading, reading, reflowTarget, updateReading, flushReading, markReflowScroll, finishReflowScroll } from './usePapers.js'
import { readerSettings } from './useReaderSettings.js'
import { layout, panelColumn } from '../dock/useLayout.js'

export function useReflowTracking(scroll, content, activeToc) {
  let foreground = true
  let frame = null
  let geometry = null
  let observer
  let locatedTarget = null
  let restoreVersion = 0
  let highlightAnimation = null
  let restoring = false
  let trackedPaperId = null
  let anchor = null
  let viewportWidth = 0

  function findBlock(id) {
    return id ? scroll.value?.querySelector(`[data-block][id="${CSS.escape(id)}"]`) : null
  }

  function blockTop(block) {
    const el = scroll.value
    return block.getBoundingClientRect().top - el.getBoundingClientRect().top - el.clientTop + el.scrollTop
  }

  function alignAnchor() {
    if (!foreground || !anchor || anchor.paperId !== activeId.value) return
    const el = scroll.value
    const block = findBlock(anchor.id)
    if (!el || !block || !el.clientHeight) return
    const top = Math.max(0, Math.min(el.scrollHeight - el.clientHeight, blockTop(block) + anchor.offset))
    // Do not restart an in-flight smooth scroll unless its destination changed.
    if (Number.isFinite(anchor.top) && Math.abs(top - anchor.top) < .5) return
    const behavior = Number.isFinite(anchor.top) ? 'instant' : anchor.behavior
    anchor.top = top
    el.scrollTo({ top, behavior })
  }

  function preservePosition() {
    if (!foreground || restoring || anchor || trackedPaperId !== activeId.value) return
    const position = reading[activeId.value]
    if (position?.reflowBlock && Number.isFinite(position.reflowBlockOffset)) {
      anchor = { paperId: activeId.value, id: position.reflowBlock, offset: position.reflowBlockOffset, behavior: 'instant' }
    }
  }

  function cancelNavigation(event) {
    if (event?.type === 'keydown' && !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
      'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) return
    if (anchor && foreground && scroll.value) {
      scroll.value.scrollTo({ top: scroll.value.scrollTop, behavior: 'instant' })
    }
    anchor = null
    // User input also takes precedence over a restore waiting for a transition.
    ++restoreVersion
    if (restoring && content.value && !loading.value) {
      trackedPaperId = activeId.value
      geometry = null
      scheduleTrack()
    }
    restoring = false
    if (reflowTarget.value?.paperId === activeId.value) locatedTarget = reflowTarget.value
  }

  function goTo(id) {
    if (!foreground || loading.value || !findBlock(id)) return
    cancelNavigation()
    clearHighlight()
    activeToc.value = id
    anchor = { paperId: activeId.value, id, offset: 0, behavior: 'smooth' }
    alignAnchor()
    scheduleTrack()
  }

  function clearHighlight() {
    highlightAnimation?.cancel()
    highlightAnimation = null
  }

  function highlightBlock(block) {
    clearHighlight()
    const style = getComputedStyle(block)
    const color = `color-mix(in srgb, ${style.getPropertyValue('--accent').trim()} 28%, transparent)`
    const animation = block.animate([
      { backgroundColor: color, offset: 0 },
      { backgroundColor: color, offset: .3 },
      { backgroundColor: style.backgroundColor, offset: 1 },
    ], { duration: 3000, easing: 'ease-out' })
    highlightAnimation = animation
    animation.onfinish = () => {
      if (highlightAnimation === animation) highlightAnimation = null
    }
  }

  function track() {
    frame = null
    const el = scroll.value
    if (!foreground || restoring || trackedPaperId !== activeId.value || !el || !paperDocument.value || loading.value) return
    const rect = el.getBoundingClientRect()
    if (!rect.height || !rect.width) return
    const top = el.scrollTop, left = el.scrollLeft
    if (!geometry) {
      geometry = indexReflowBlocks([...el.querySelectorAll('[data-block]')].map(block => {
        const bounds = block.getBoundingClientRect()
        return { id: block.id, page: Number(block.dataset.page), heading: block.hasAttribute('data-heading'),
          top: bounds.top - rect.top + top, bottom: bounds.bottom - rect.top + top,
          left: bounds.left - rect.left + left, right: bounds.right - rect.left + left }
      }))
    }
    const position = readReflowPosition(geometry, { top, bottom: top + rect.height, left, right: left + rect.width },
      reading[activeId.value]?.reflowPage || 1)
    if (position.blockId) updateReading({ reflowBlock: position.blockId, reflowOffset: top, reflowBlockOffset: position.blockOffset,
      reflowPage: position.page, reflowPageProgress: position.progress,
      progress: Math.round(top / Math.max(1, el.scrollHeight - el.clientHeight) * 100) })
    activeToc.value = position.headingId || ''
  }
  function scheduleTrack() {
    if (foreground && frame === null) frame = requestAnimationFrame(track)
  }
  function onScroll() {
    if (!foreground || restoring || trackedPaperId !== activeId.value || !paperDocument.value || loading.value) return
    markReflowScroll()
    scheduleTrack()
  }
  function invalidateGeometry() {
    geometry = null
    if (!restoring) alignAnchor()
    scheduleTrack()
  }
  function onVisibilityChange() {
    if (document.visibilityState === 'hidden') {
      cancelAnimationFrame(frame)
      track()
      flushReading()
    } else invalidateGeometry()
  }
  function suspend() {
    foreground = false
    anchor = null
    restoring = false
    ++restoreVersion
    clearHighlight()
    cancelAnimationFrame(frame)
    frame = null
    finishReflowScroll()
  }
  async function restore() {
    const version = ++restoreVersion
    const paperId = activeId.value
    if (!foreground) return
    const position = { ...reading[paperId] }
    restoring = true
    anchor = null
    geometry = null
    await nextTick()
    if (!foreground || version !== restoreVersion || activeId.value !== paperId) return
    if (!paperDocument.value || loading.value || !content.value) {
      restoring = false
      return
    }
    const target = reflowTarget.value
    const pendingTarget = target && target !== locatedTarget && target.paperId === paperId
    // Restoring a saved position needs the final column width just as a new
    // source jump does. ResizeObserver handles subsequent TOC/font/image layout.
    const transitions = scroll.value?.closest('.dock-column')?.getAnimations()
      .filter(animation => animation.transitionProperty === 'width') || []
    await Promise.allSettled(transitions.map(animation => animation.finished))
    if (!foreground || version !== restoreVersion || activeId.value !== paperId) return
    const block = pendingTarget ? findBlock(target.id) : null
    if (block) {
      anchor = { paperId, id: target.id, offset: 0, behavior: 'instant' }
      alignAnchor()
      highlightBlock(block)
      locatedTarget = target
    } else if (scroll.value) {
      if (Number.isFinite(position.reflowBlockOffset) && findBlock(position.reflowBlock)) {
        anchor = { paperId, id: position.reflowBlock, offset: position.reflowBlockOffset, behavior: 'instant' }
        alignAnchor()
      } else scroll.value.scrollTo({ top: position.reflowOffset || 0, behavior: 'instant' })
    }
    trackedPaperId = paperId
    restoring = false
    scheduleTrack()
  }
  onMounted(() => {
    observer = new ResizeObserver(() => {
      const width = scroll.value?.clientWidth
      if (width && viewportWidth && width !== viewportWidth) preservePosition()
      if (width) viewportWidth = width
      invalidateGeometry()
    })
    observer.observe(scroll.value)
    if (content.value) observer.observe(content.value)
    document.fonts?.addEventListener('loadingdone', invalidateGeometry)
    document.addEventListener('visibilitychange', onVisibilityChange)
    scheduleTrack()
  })
  watch(content, (el, previous) => {
    if (previous) observer?.unobserve(previous)
    if (el) observer?.observe(el)
    invalidateGeometry()
  }, { flush: 'post' })
  watch([activeId, paperDocument, loading, reflowTarget], restore)
  // KeepAlive's deactivation hook runs after the DOM has been detached. Capture
  // a pending scroll while the panel still has its original width and height.
  watch(() => {
    const column = layout.columns[panelColumn('reflow')]
    return column?.active === 'reflow' && !column.collapsed
  }, visible => {
    if (!visible && foreground) { cancelAnimationFrame(frame); track() }
  }, { flush: 'sync' })
  watch([activeId, paperDocument], clearHighlight)
  watch(() => [readerSettings.titleFontSize, readerSettings.fontSize, readerSettings.lineHeight, readerSettings.showPageAnchors], async () => {
    cancelAnimationFrame(frame)
    track()
    preservePosition()
    await nextTick()
    invalidateGeometry()
  })
  onActivated(() => { foreground = true; restore() })
  onDeactivated(suspend)
  onBeforeUnmount(() => {
    suspend()
    observer?.disconnect()
    document.fonts?.removeEventListener('loadingdone', invalidateGeometry)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })
  return { onScroll, invalidateGeometry, goTo, cancelNavigation }
}
