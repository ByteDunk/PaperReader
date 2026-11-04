<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import SettingsItem from './SettingsItem.vue'
import IconButton from './IconButton.vue'
import { requestJson } from '../services/http.js'

const form = defineModel({ type: Object, required: true })
const props = defineProps({ configured: Boolean, disabled: Boolean, revision: String })
const keyVisible = ref(false)
const revealedKey = ref('')
const revealing = ref(false)
const keyError = ref('')
const displayedKey = computed(() => form.value.api_key || revealedKey.value)
let revealController

function abortReveal() {
  revealController?.abort()
  revealController = null
  revealing.value = false
}

function concealKey() {
  abortReveal()
  keyVisible.value = false
  revealedKey.value = keyError.value = ''
}

function updateKey(event) {
  abortReveal()
  form.value.api_key = event.target.value
  revealedKey.value = keyError.value = ''
  if (!form.value.api_key) keyVisible.value = false
}

async function toggleKeyVisibility() {
  if (props.disabled || revealing.value) return
  if (keyVisible.value) { concealKey(); return }
  keyError.value = ''
  if (form.value.api_key || !props.configured) { keyVisible.value = true; return }
  const controller = revealController = new AbortController()
  revealing.value = true
  try {
    const result = await requestJson(`/api/llm/settings/api-key?revision=${encodeURIComponent(props.revision)}`, { signal: controller.signal })
    if (controller.signal.aborted) return
    revealedKey.value = result.api_key
    keyVisible.value = true
  } catch (error) {
    if (!controller.signal.aborted) keyError.value = error.message
  } finally {
    if (revealController === controller) { revealController = null; revealing.value = false }
  }
}

watch(() => props.disabled, disabled => { if (disabled) concealKey() })
watch(() => props.revision, concealKey)
onBeforeUnmount(concealKey)
</script>

<template>
  <fieldset class="api-fields" :disabled="disabled">
    <SettingsItem label="API 地址" for-id="settings-api-url">
      <input id="settings-api-url" v-model="form.base_url" type="url" maxlength="2048" placeholder="填写 API 地址" />
    </SettingsItem>
    <SettingsItem label="模型名称" for-id="settings-api-model">
      <input id="settings-api-model" v-model="form.model" maxlength="200" placeholder="填写模型名称" />
    </SettingsItem>
    <SettingsItem label="API Key" for-id="settings-api-key">
      <input id="settings-api-key" class="api-key-input" :class="{ 'has-saved-key': configured && !displayedKey }"
        :value="displayedKey" :type="keyVisible ? 'text' : 'password'" autocomplete="new-password" spellcheck="false" autocapitalize="none"
        :placeholder="configured ? '••••••••••••••••' : '填写 API Key'" @input="updateKey" />
      <IconButton class="key-visibility" :icon="revealing ? 'loader' : keyVisible ? 'eye-off' : 'eye'"
        :class="{ spin: revealing }" :title="keyVisible ? '隐藏 API Key' : '显示 API Key'"
        :aria-label="keyVisible ? '隐藏 API Key' : '显示 API Key'" :aria-pressed="keyVisible" :aria-busy="revealing"
        aria-controls="settings-api-key" :disabled="disabled || revealing || (!configured && !form.api_key)" @click="toggleKeyVisibility" />
    </SettingsItem>
    <p v-if="keyError" class="key-error" role="alert">{{ keyError }}</p>
  </fieldset>
</template>

<style scoped>
.api-fields { display: flex; flex-direction: column; gap: 18px; border: 0; padding: 0; margin: 0; min-width: 0; }
.api-fields :deep(.ui-field) { height: 36px; }
.key-visibility { --icon-button-size: 24px; margin-right: -6px; }
.api-key-input.has-saved-key::placeholder { color: var(--text); letter-spacing: 2px; opacity: 1; }
.api-key-input::-ms-reveal { display: none; }
.key-error { margin: 0; color: var(--danger); font-size: 12px; overflow-wrap: anywhere; }
</style>
