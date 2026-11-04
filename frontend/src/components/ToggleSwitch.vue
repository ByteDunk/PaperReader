<script setup>
const checked = defineModel({ type: Boolean, default: false })
</script>

<template>
  <button type="button" class="toggle-switch" role="switch" :aria-checked="checked"
    @click="checked = !checked">
    <span class="switch-thumb" />
  </button>
</template>

<style scoped>
.toggle-switch {
  display: inline-flex;
  align-items: center;
  flex: none;
  width: 34px;
  height: 20px;
  padding: 3px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--surface-3);
  transition: background-color .18s ease, border-color .18s ease;
}
.switch-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text-3);
  transition: transform .18s ease, background-color .18s ease;
}
.toggle-switch[aria-checked='true'] {
  background: var(--accent-soft);
  border-color: var(--accent);
}
.toggle-switch[aria-checked='true'] .switch-thumb {
  transform: translateX(14px);
  background: var(--accent);
}
@media (prefers-reduced-motion: reduce) {
  .toggle-switch, .switch-thumb { transition: none; }
}
</style>
