<script setup>
import SettingsItem from './SettingsItem.vue'

const props = defineProps({ id: String, label: String, description: String,
  min: Number, max: Number, unit: String, divisor: { type: Number, default: 1 } })
const value = defineModel({ type: Number })
const format = number => props.divisor === 1 ? number : (number / props.divisor).toFixed(1)
</script>

<template>
  <SettingsItem :label="label" :for-id="id" :description="description" unframed>
    <div class="range-control">
      <span class="range-limit" aria-hidden="true">{{ format(min) }}</span>
      <input :id="id" v-model.number="value" type="range" :min="min" :max="max" step="1"
        :aria-describedby="`${id}-hint`" :aria-valuetext="`${format(value)} ${unit}`" />
      <span class="range-limit" aria-hidden="true">{{ format(max) }}</span>
      <output :for="id">{{ format(value) }} {{ unit }}</output>
    </div>
  </SettingsItem>
</template>

<style scoped>
.range-control { display: flex; align-items: center; gap: 8px; width: 100%; height: 100%; }
.range-control input { flex: 1; }
.range-control output { flex: none; width: 58px; color: var(--accent); font-size: 12.5px; font-variant-numeric: tabular-nums; text-align: right; }
.range-limit { flex: none; min-width: 14px; color: var(--text-3); font-size: 10.5px; line-height: 14px; font-variant-numeric: tabular-nums; text-align: center; }
@media (max-width: 420px) {
  .range-control { gap: 5px; }
  .range-control output { width: 46px; font-size: 12px; }
}
</style>
