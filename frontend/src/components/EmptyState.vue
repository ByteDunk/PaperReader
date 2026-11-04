<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, required: true },
  hint: { type: String, default: '' },
})
</script>

<template>
  <div class="empty">
    <span class="empty-icon"><AppIcon :name="icon" :size="20" /></span>
    <p class="empty-title">{{ title }}</p>
    <p v-if="hint" class="empty-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 22px 16px;
  text-align: center;
}
.empty-icon {
  display: inline-flex;
  padding: 10px;
  border-radius: var(--radius);
  background: var(--surface-3);
  color: var(--text-3);
  margin-bottom: 4px;
}
.empty-title {
  margin: 0;
  font-size: 12.5px;
  font-weight: 550;
  color: var(--text-2);
}
.empty-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-3);
}
</style>
