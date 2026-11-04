<script setup>
defineProps({ label: { type: String, required: true }, forId: String, description: String, unframed: Boolean })
</script>

<template>
  <div class="settings-item">
    <div class="item-heading">
      <label :for="forId">{{ label }}</label>
    </div>
    <p v-if="description" :id="forId ? `${forId}-hint` : undefined" class="item-description">{{ description }}</p>
    <div class="item-control" :class="{ 'ui-field': !unframed }"><slot /></div>
  </div>
</template>

<style scoped>
.settings-item { display: flex; flex-direction: column; gap: 8px; min-width: 0; font-size: 12.5px; }
.item-heading { display: flex; align-items: center; min-height: 22px; }
.item-heading label { color: var(--text); font-weight: 550; }
.item-description { margin: -4px 0 0; color: var(--text-3); font-size: 11px; line-height: 1.65; }
.item-control:not(.ui-field) { display: flex; align-items: center; height: var(--control-height); min-width: 0; }
</style>
