<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

defineProps({ step: { type: Object, required: true } })
const frame = ref(null)
const visible = ref(false)
const active = ref(true)
const preview = ref(null)
const previewOpen = ref(false)
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)')
const playing = ref(!motionPreference.matches)
const animating = computed(() => playing.value && visible.value && active.value)
let observer
function updateMotion(event) { playing.value = !event.matches }
function openPreview() {
  previewOpen.value = true
  preview.value.showModal()
}
onMounted(() => {
  observer = new IntersectionObserver(([entry]) => { visible.value = entry.isIntersecting })
  observer.observe(frame.value)
  motionPreference.addEventListener('change', updateMotion)
})
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false; preview.value?.close() })
onBeforeUnmount(() => {
  observer?.disconnect()
  motionPreference.removeEventListener('change', updateMotion)
})
</script>

<template>
  <div ref="frame" class="demo-frame">
    <img :src="animating ? step.animation : step.poster" :alt="`${step.title}的操作演示`" width="1120" height="700" loading="lazy" decoding="async" />
    <div class="demo-controls">
      <button type="button" :aria-label="`放大查看：${step.title}`" @click="openPreview"><AppIcon name="maximize" :size="13" />放大</button>
      <button type="button" :aria-label="`${playing ? '暂停' : '播放'}演示：${step.title}`" :aria-pressed="playing" @click="playing = !playing">
        <AppIcon :name="playing ? 'pause' : 'play'" :size="13" />{{ playing ? '暂停演示' : '播放演示' }}
      </button>
    </div>
  </div>
  <Teleport to="body">
    <dialog ref="preview" class="demo-preview" :aria-label="step.title" @close="previewOpen = false" @click.self="preview.close()">
      <header><span>{{ step.title }}</span><button type="button" aria-label="关闭放大演示" @click="preview.close()"><AppIcon name="x" :size="18" /></button></header>
      <img v-if="previewOpen" :src="playing ? step.animation : step.poster" :alt="`${step.title}的放大操作演示`" width="1120" height="700" />
    </dialog>
  </Teleport>
</template>

<style scoped>
.demo-frame { position: relative; overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2); }
img { display: block; width: 100%; height: auto; }
.demo-controls { position: absolute; right: 8px; bottom: 8px; display: flex; gap: 5px; }
.demo-controls button { display: flex; align-items: center; gap: 5px; padding: 5px 9px; border: 1px solid var(--border-strong); border-radius: var(--radius-s); background: var(--surface); color: var(--text); font-size: 11px; box-shadow: var(--shadow-sm); }
.demo-controls button:hover { background: var(--surface-3); }
.demo-preview { width: min(1152px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-l); background: var(--surface); color: var(--text); }
.demo-preview::backdrop { background: #101420b3; }
.demo-preview header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.demo-preview header button { display: inline-flex; padding: 4px; }
.demo-preview img { max-height: calc(100dvh - 108px); object-fit: contain; }
</style>
