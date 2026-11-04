<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, useAttrs, watch } from 'vue'

const props = defineProps({
  src: { type: String, required: true },
  sourceWidth: { type: Number, default: 0 },
})
const emit = defineEmits(['load', 'error'])
const attrs = useAttrs()
const naturalRatio = ref(0)
const aspectRatio = computed(() => naturalRatio.value || (attrs.width && attrs.height ? attrs.width / attrs.height : 1))
// Broken images ignore their declared aspect ratio in Chromium. Keep a valid
// empty image, including the measured ratio after an offscreen bitmap is freed.
const placeholder = computed(() => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${aspectRatio.value} 1"/>`)}`)
const image = ref(null)
const displayedUrl = ref()
let visible = false
let active = true
let timer, intersection, resize, densityQuery, controller
let version = 0, loadedScale = 0, pendingScale = 0
let inferredWidth = 0

function cancelRequest() {
  clearTimeout(timer)
  controller?.abort()
  controller = null
  pendingScale = 0
  ++version
}
function release() {
  cancelRequest()
  if (displayedUrl.value) URL.revokeObjectURL(displayedUrl.value)
  displayedUrl.value = undefined
  loadedScale = 0
}
function schedule() {
  clearTimeout(timer)
  if (visible && active) timer = setTimeout(load, 140)
}
async function load() {
  if (!visible || !active || !image.value) return
  const width = image.value.getBoundingClientRect().width
  if (!width) return
  const sourceWidth = props.sourceWidth || inferredWidth
  const required = sourceWidth > 0 ? width * (window.devicePixelRatio || 1) / sourceWidth : 2
  const scale = [1, 2, 3, 4, 6, 8].find(tier => tier >= required) || 8
  if (loadedScale >= scale || pendingScale === scale) return
  cancelRequest()
  const ticket = version
  const request = controller = new AbortController()
  pendingScale = scale
  const base = props.src
  let objectUrl
  try {
    const response = await fetch(`${base}${base.includes('?') ? '&' : '?'}scale=${scale}`, { signal: request.signal })
    if (!response.ok) throw new Error(`图片加载失败（${response.status}）`)
    objectUrl = URL.createObjectURL(await response.blob())
    const probe = new Image()
    probe.src = objectUrl
    await probe.decode()
    if (ticket !== version || !visible || !active) return
    naturalRatio.value = probe.naturalWidth / probe.naturalHeight
    if (!props.sourceWidth) inferredWidth = probe.naturalWidth / scale
    if (displayedUrl.value) URL.revokeObjectURL(displayedUrl.value)
    displayedUrl.value = objectUrl
    objectUrl = null
    loadedScale = scale
    schedule()
  } catch (error) {
    if (ticket === version && error.name !== 'AbortError' && !displayedUrl.value) emit('error', error)
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    if (ticket === version) { pendingScale = 0; controller = null }
  }
}
function watchDensity() {
  densityQuery?.removeEventListener('change', watchDensity)
  densityQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
  densityQuery.addEventListener('change', watchDensity)
  schedule()
}
onMounted(() => {
  intersection = new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting
    if (visible) schedule()
    else release()
  }, { root: image.value.closest('.page-scroll, .reflow-scroll, .trans-body'), rootMargin: '160px' })
  intersection.observe(image.value)
  resize = new ResizeObserver(schedule)
  resize.observe(image.value)
  watchDensity()
})
watch(() => props.src, () => { release(); naturalRatio.value = 0; inferredWidth = 0; schedule() })
watch(() => props.sourceWidth, schedule)
onActivated(() => { active = true; schedule() })
onDeactivated(() => { active = false; release() })
onBeforeUnmount(() => {
  active = false
  release()
  intersection?.disconnect()
  resize?.disconnect()
  densityQuery?.removeEventListener('change', watchDensity)
})
</script>

<template>
  <img ref="image" :src="displayedUrl || placeholder" decoding="async"
    :style="{ aspectRatio }"
    @load="emit('load', $event)" @error="emit('error', $event)" />
</template>
