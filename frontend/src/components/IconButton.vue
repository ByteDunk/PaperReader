<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  icon: { type: String, required: true },
  title: { type: String, default: '' },
  size: { type: [Number, String], default: 15 },
  active: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
defineEmits(['click'])
</script>

<template>
  <button
    type="button"
    class="icon-btn"
    :class="{ active }"
    :title="title"
    :disabled="disabled"
    @click="$emit('click')"
  >
    <AppIcon :name="icon" :size="size" />
  </button>
</template>
