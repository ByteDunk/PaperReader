export function paperStatus(paper) {
  if (paper.state === 'parsing') return { text: `解析中 ${Math.round(paper.parse_progress || 0)}%`, tone: 'amber' }
  if (paper.state === 'failed') return { text: '重排失败', tone: 'red' }
  const translation = paper.translation
  const index = paper.index
  if (paper.state === 'ready') {
    if (translation?.state === 'failed') return { text: `翻译失败 ${translation.progress || 0}%`, tone: 'red' }
    if (index?.state === 'failed') return { text: '索引失败', tone: 'red' }
    if (translation?.state === 'translating') return { text: `翻译中 ${translation.progress || 0}%`, tone: 'blue' }
    if (index && index.state !== 'ready') return { text: `索引中 ${Math.round(index.progress || 0)}%`, tone: 'purple' }
    if (translation?.state === 'waiting') return { text: '待翻译', tone: 'gray' }
    if (translation?.state === 'unconfigured') return { text: '待配置 API', tone: 'gray' }
  }
  return { text: paper.state === 'ready' ? '已就绪' : '未解析', tone: paper.state === 'ready' ? 'green' : 'gray' }
}

export function paperStatusDetails(paper) {
  const labels = { parsing: '进行中', translating: '进行中', indexing: '进行中', queued: '排队中',
    ready: '已完成', done: '已完成', failed: '失败', waiting: '等待开始', unconfigured: '待配置 API', unparsed: '未解析' }
  return [
    ['解析', { state: paper.state, progress: paper.parse_progress, error: paper.error }],
    ['翻译', paper.translation],
    ['索引', paper.index],
  ].map(([name, task]) => {
    if (!task) return `${name}：${paper.state === 'ready' ? '未开始' : '等待解析'}`
    const progress = ['ready', 'done', 'unparsed'].includes(task.state) ? '' : ` ${Math.round(task.progress || 0)}%`
    return `${name}：${labels[task.state] || '未开始'}${progress}${task.error ? `\n  ${task.error}` : ''}`
  }).join('\n')
}

// Page visibility is based on clipped block area, rather than the first block
// intersecting the viewport. Ties keep the previous page to avoid flickering.
export function dominantPage(blocks, viewport, previous = 1) {
  const scores = new Map()
  for (const block of blocks) {
    const height = Math.max(0, Math.min(block.bottom, viewport.bottom) - Math.max(block.top, viewport.top))
    const width = Math.max(0, Math.min(block.right, viewport.right) - Math.max(block.left, viewport.left))
    if (height && width) scores.set(block.page, (scores.get(block.page) || 0) + height * width)
  }
  let page = previous
  let maximum = scores.get(previous) || 0
  for (const [candidate, area] of scores) {
    if (area > maximum) { maximum = area; page = candidate }
  }
  return page
}
