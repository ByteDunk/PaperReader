<script setup>
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '' },
  defaultOpen: { type: Boolean, default: false },
})

const open = ref(props.defaultOpen)
defineExpose({ expand: () => { open.value = true } })
</script>

<template>
  <section class="collapse" :class="{ open }">
    <button class="collapse-head" @click="open = !open">
      <AppIcon v-if="icon" :name="icon" :size="14" class="head-icon" />
      <span class="collapse-title">{{ title }}</span>
      <span class="spacer" />
      <AppIcon name="chevron-down" :size="14" class="chev" />
    </button>
    <div v-show="open" class="collapse-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.collapse {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
}
.collapse-head {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  height: var(--control-height);
  padding: 0 12px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  transition: background-color 0.15s ease, color 0.15s ease;
}
.collapse-head:hover {
  background: var(--surface-2);
  color: var(--text);
}
.open .collapse-head {
  color: var(--text);
}
.head-icon {
  color: var(--text-3);
}
.chev {
  color: var(--text-3);
  transition: transform 0.2s ease;
}
.open .chev {
  transform: rotate(180deg);
}
.collapse-body {
  padding: 4px 12px 12px;
  border-top: 1px solid var(--border);
}
</style>
