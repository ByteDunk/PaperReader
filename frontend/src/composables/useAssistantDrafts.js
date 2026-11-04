import { reactive } from 'vue'
import { openPanel } from '../dock/useLayout.js'
import { blockReference, MAX_ATTACHED_REFERENCES } from '../services/assistant.js'

export const assistantDrafts = reactive({})

export function assistantDraft(paperId) {
  return assistantDrafts[paperId] ||= { text: '', references: [], notice: '' }
}

export function attachAssistantReference(paperId, block) {
  if (!paperId || !block?.id) return
  const draft = assistantDraft(paperId)
  draft.notice = ''
  if (!draft.references.some(reference => reference.id === block.id)) {
    if (draft.references.length >= MAX_ATTACHED_REFERENCES) draft.notice = `每次最多附加 ${MAX_ATTACHED_REFERENCES} 条引用，请先移除部分引用。`
    else draft.references.push(blockReference(paperId, block))
  }
  openPanel('assistant')
}

export function removeAssistantReference(paperId, blockId) {
  const draft = assistantDraft(paperId)
  draft.references = draft.references.filter(reference => reference.id !== blockId)
  draft.notice = ''
}
