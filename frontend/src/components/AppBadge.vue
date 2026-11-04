<script setup>
defineProps({
  tone: { type: String, default: 'gray' }, // gray | green | blue | purple | amber | red
})
</script>

<template>
  <span class="badge" :class="`tone-${tone}`"><slot /></span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  line-height: 1.4;
  padding: 1px 8px;
  border-radius: 99px;
  background: var(--surface-3);
  color: var(--text-2);
  white-space: nowrap;
}
.tone-green {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}
.tone-blue {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
}
.tone-purple {
  background: color-mix(in srgb, var(--indexing) 13%, transparent);
  color: var(--indexing);
}
.tone-amber {
  background: color-mix(in srgb, var(--warning) 14%, transparent);
  color: var(--warning);
}
.tone-red {
  background: color-mix(in srgb, var(--danger) 13%, transparent);
  color: var(--danger);
}
</style>
