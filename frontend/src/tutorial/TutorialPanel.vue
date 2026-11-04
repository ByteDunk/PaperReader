<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import TutorialDemo from './TutorialDemo.vue'
import { steps } from './content.js'
import { closeTutorial } from '../dock/useLayout.js'

const scroll = ref(null)
const storageKey = 'paperreader.tutorial.scroll'
let position = 0, finished = false
try { position = Number(localStorage.getItem(storageKey)) || 0 } catch {}
function remember(event) {
  if (event.target.clientHeight) position = event.target.scrollTop
}
function save() {
  try {
    if (finished) localStorage.removeItem(storageKey)
    else localStorage.setItem(storageKey, String(position))
  } catch {}
}
function finish() {
  finished = true
  save()
  closeTutorial()
}
onActivated(() => { scroll.value.scrollTop = position })
onDeactivated(save)
onMounted(() => window.addEventListener('pagehide', save))
onBeforeUnmount(() => { save(); window.removeEventListener('pagehide', save) })
</script>

<template>
  <div ref="scroll" class="tutorial-panel" @scroll.passive="remember">
    <article class="tutorial-content" aria-labelledby="tutorial-title">
      <header class="tutorial-header">
        <span class="tutorial-kicker"><AppIcon name="book-open" :size="16" />使用教程</span>
        <h1 id="tutorial-title">快速上手</h1>
      </header>
      <section v-for="(step, index) in steps" :key="step.id" class="tutorial-step" :aria-labelledby="`tutorial-${step.id}`">
        <h2 :id="`tutorial-${step.id}`"><span>{{ String(index + 1).padStart(2, '0') }}</span>{{ step.title }}</h2>
        <figure>
          <TutorialDemo :step="step" />
          <figcaption>
            <p v-for="paragraph in step.description" :key="paragraph">{{ paragraph }}</p>
          </figcaption>
        </figure>
      </section>
      <footer class="tutorial-footer">
        <button type="button" class="ui-button ui-button--primary" @click="finish">
          <AppIcon name="check" :size="15" />我已了解，关闭页面
        </button>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.tutorial-panel { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; container-type: inline-size; }
.tutorial-content { width: 100%; max-width: 1040px; margin: 0 auto; padding: 32px clamp(16px, 4cqi, 40px) 24px; }
.tutorial-header { margin-bottom: 28px; }
.tutorial-kicker { display: inline-flex; align-items: center; gap: 7px; color: var(--accent); font-size: 12px; font-weight: 600; }
h1 { margin: 10px 0 12px; font-size: clamp(20px, 3.5cqi, 28px); line-height: 1.4; letter-spacing: -.3px; }
p { margin: 10px 0 0; color: color-mix(in srgb, var(--text) 35%, var(--text-2)); font-size: 14px; line-height: 1.4; overflow-wrap: anywhere; }
.tutorial-step + .tutorial-step { margin-top: 32px; padding-top: 28px; border-top: 1px solid var(--border); }
figure { margin: 0; }
figcaption { padding: 18px 2px 0; }
h2 { display: flex; align-items: baseline; gap: 10px; margin: 0 0 12px; font-size: 16px; line-height: 1.6; }
h2 span { color: var(--accent); font-size: 12px; font-variant-numeric: tabular-nums; }
.tutorial-footer { display: flex; justify-content: flex-end; margin-top: 32px; padding-top: 20px; border-top: 1px solid var(--border); }
.tutorial-footer button { height: auto; min-height: 36px; white-space: normal; text-align: left; }
</style>
