<script setup>
import { activeId } from '../composables/usePapers'
import PdfAsset from './PdfAsset.vue'

defineProps({ text: { type: String, default: '' }, spans: { type: Array, default: null } })
</script>

<template>
  <template v-if="spans?.length">
    <component :is="span.script === 'sub' ? 'sub' : span.script === 'sup' ? 'sup' : 'span'" v-for="(span, index) in spans" :key="index">
      <PdfAsset v-if="span.asset" :paper-id="activeId" :block="span" inline />
      <strong v-else-if="span.bold">{{ span.text }}</strong><template v-else>{{ span.text }}</template>
    </component>
  </template>
  <template v-else>{{ text }}</template>
</template>
