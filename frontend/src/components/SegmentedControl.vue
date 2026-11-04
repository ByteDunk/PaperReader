<script setup>
defineProps({
  options: { type: Array, required: true }, // [{ value, label }]
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="seg" role="tablist">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      class="seg-item"
      role="tab"
      :aria-selected="o.value === modelValue"
      :disabled="disabled"
      :class="{ active: o.value === modelValue }"
      @click="emit('update:modelValue', o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>

<style scoped>
.seg {
  display: inline-flex;
  max-width: 100%;
  height: var(--control-height);
  padding: 2px;
  gap: 2px;
  border-radius: var(--radius);
  background: var(--surface-3);
}
.seg-item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 11px;
  border-radius: calc(var(--radius) - 3px);
  font-size: 12px;
  white-space: nowrap;
  color: var(--text-2);
  transition: background-color 0.15s ease, color 0.15s ease;
}
.seg-item:hover:not(:disabled) {
  color: var(--text);
}
.seg-item.active {
  background: var(--surface);
  color: var(--text);
  font-weight: 550;
  box-shadow: var(--shadow-sm);
}
</style>
