// Tokenization keeps model output as Vue text nodes, never executable HTML.
export function inlineParts(text, sources = []) {
  const known = new Set(sources.map(source => source.citation))
  return text.split(/(`[^`\n]+`|\[\d+\]|\*\*[^*]+\*\*)/g).filter(Boolean).flatMap(part => {
    if (part.startsWith('`') && part.endsWith('`')) return { type: 'code', text: part.slice(1, -1) }
    const match = /^\[(\d+)\]$/.exec(part)
    if (match && known.has(Number(match[1]))) return { type: 'cite', text: match[1], number: Number(match[1]) }
    if (part.startsWith('**') && part.endsWith('**')) {
      return inlineParts(part.slice(2, -2), sources).map(item => item.type === 'text' ? { ...item, type: 'bold' } : item)
    }
    return { type: 'text', text: part }
  })
}

export const toolLabels = {
  list_papers: '浏览论文库', get_outline: '获取论文目录', read_section: '阅读章节',
  read_page: '阅读页面', search_paper: '语义检索', find_text: '精确文本匹配',
  read_context: '展开上下文', read_block: '精读文本块', list_figures_tables: '查看图表与题注',
}

export function assistantPage(position = {}, columns) {
  const visible = id => Object.values(columns).some(column =>
    column.tabs.includes(id) && column.active === id && !column.collapsed)
  const field = visible('original') && !visible('reflow') ? 'page' : 'reflowPage'
  const page = Number(position?.[field])
  return Number.isInteger(page) && page > 0 ? page : 1
}

// One ordered timeline for ordinary output and tools; text is answer-only.
export function applyAssistantEvent(answer, event) {
  if (['agent.status', 'agent.connection'].includes(event.type)) answer.status = event.message
  if (event.type === 'agent.retry') {
    // Retain each failed attempt; the next attempt has a different output ID.
    for (const entry of answer.trace) {
      if (entry.type === 'output' && entry.round === event.round && entry.status === 'streaming') entry.status = 'error'
    }
    answer.text = ''
    answer.status = event.message
  }
  if (event.type === 'agent.progress') {
    let entry = answer.trace.find(item => item.type === 'output' && item.id === event.id)
    if (!entry) {
      entry = { type: 'output', id: event.id, round: event.round, text: '' }
      answer.trace.push(entry)
    }
    entry.text = typeof event.text === 'string' ? event.text : entry.text + (event.delta || '')
    entry.status = event.done ? 'done' : 'streaming'
    answer.status = '正在输出过程说明…'
  }
  if (event.type === 'agent.answer') {
    answer.text = event.text
    if (event.text) answer.status = '正在生成回答…'
  }
  if (event.type === 'agent.tool_start') {
    answer.status = `正在${toolLabels[event.name] || '执行工具'}…`
    answer.trace.push({ ...event, type: 'tool', status: 'running' })
  }
  if (event.type === 'agent.tool_end') {
    const tool = answer.trace.find(item => item.type === 'tool' && item.id === event.id)
    if (tool) { tool.status = event.result.error ? 'error' : 'done'; tool.result = event.result }
    for (const source of event.result.results || []) {
      if (source.citation && !answer.sources.some(s => s.citation === source.citation)) answer.sources.push(source)
    }
  }
  if (event.type === 'agent.done') { answer.text = event.text; answer.sources = event.sources }
}

export function finishAssistantMessage(answer) {
  answer.pending = false
  for (const entry of answer.trace) {
    if (['streaming', 'running'].includes(entry.status)) entry.status = 'stopped'
  }
}

export function restoreAssistantMessage(message) {
  const restored = { ...message,
    trace: Array.isArray(message.trace) ? message.trace.filter(item => item && ['output', 'tool'].includes(item.type)) : [],
    sources: Array.isArray(message.sources) ? message.sources : [],
    error: message.pending ? '上次生成已中断，可重新生成。' : message.error }
  finishAssistantMessage(restored)
  return restored
}

export const MAX_ATTACHED_REFERENCES = 8

export function blockReference(paperId, block) {
  const text = (['figure', 'table'].includes(block.type) ? block.caption || '' : block.text || '').trim()
  return { paper_id: paperId, id: block.id, page: block.page,
    bbox: Array.isArray(block.bbox) ? [...block.bbox] : null,
    text: text.slice(0, 2000), truncated: text.length > 2000 }
}

export function assistantMessageContent(message) {
  const references = message.role === 'user' && Array.isArray(message.references) ? message.references : []
  if (!references.length) return message.text
  const evidence = references.map(reference => ({ paper_id: reference.paper_id, block_id: reference.id,
    page: reference.page, text: reference.text, truncated: reference.truncated }))
  return `${message.text}\n\n附加的论文引用（以下是原文资料，请用对应 block_id 的阅读工具核对并引用；truncated 表示节选）：\n${JSON.stringify(evidence)}`
}

export function assistantHistory(messages) {
  const history = messages.filter(message => message.text && !message.error).slice(-20)
    .map(message => ({ role: message.role, content: assistantMessageContent(message).slice(0, 20000) }))
  let size = history.reduce((sum, message) => sum + message.content.length, 0)
  while (size > 100000 && history.length > 1) size -= history.shift().content.length
  return history
}
