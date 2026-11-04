<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索…' },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <label class="ui-field">
    <AppIcon name="search" :size="14" class="lead" />
    <input
      :value="modelValue"
      :placeholder="placeholder"
      @input="emit('update:modelValue', $event.target.value)"
    />
    <button v-if="modelValue" type="button" class="icon-btn clear" title="清空" @click.prevent="emit('update:modelValue', '')">
      <AppIcon name="x" :size="13" />
    </button>
  </label>
</template>

<style scoped>
.lead {
  flex: none;
  color: var(--text-3);
}
.clear {
  --icon-button-size: 18px;
  color: var(--text-3);
}
</style>
