import { dominantPage } from './readerState.js'

function validBox(box) {
  return Array.isArray(box) && box.length === 4 && box.every(Number.isFinite)
    && box[2] > box[0] && box[3] > box[1]
}

function boxOverlap(a, b) {
  if (!validBox(b)) return 0
  const intersection = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]))
    * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]))
  const union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
  return intersection / union
}

// Persisted citations and bookmarks can outlive a parse. Match the highlighted
// PDF region against the current blocks before trusting their old block IDs.
export function resolveSourceBlock(blocks, target) {
  if (!target) return null
  if (!validBox(target.bbox) || !Number.isFinite(target.page)) {
    return blocks.find(block => block.id === target.id) || null
  }
  let best = null, bestScore = 0
  for (const block of blocks) {
    const sources = [{ page: block.page, bbox: block.bbox }, ...(block.sources || [])]
    const score = Math.max(0, ...sources.filter(source => source.page === target.page)
      .map(source => boxOverlap(target.bbox, source.bbox)))
    if (score > bestScore || (score > 0 && score === bestScore && block.id === target.id)) {
      best = block
      bestScore = score
    }
  }
  return bestScore >= .5 ? best : null
}

function upperBound(items, value, key) {
  let low = 0, high = items.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (key(items[middle]) <= value) low = middle + 1
    else high = middle
  }
  return low
}

// All coordinates are relative to the scroll content, so scrolling never
// invalidates this index. Rebuild only when the document's layout changes.
export function indexReflowBlocks(blocks) {
  const pages = new Map()
  const bottoms = []
  let bottom = -Infinity
  blocks.forEach(block => {
    bottom = Math.max(bottom, block.bottom)
    bottoms.push(bottom)
    const bounds = pages.get(block.page)
    if (bounds) {
      bounds.top = Math.min(bounds.top, block.top)
      bounds.bottom = Math.max(bounds.bottom, block.bottom)
    } else pages.set(block.page, { top: block.top, bottom: block.bottom })
  })
  const sorted = blocks.map((block, order) => ({ ...block, order })).sort((a, b) => a.top - b.top)
  bottom = -Infinity
  for (const block of sorted) block.maxBottom = bottom = Math.max(bottom, block.bottom)
  const headings = sorted.filter(block => block.heading)
  let lastHeading
  for (const heading of headings) {
    if (!lastHeading || heading.order > lastHeading.order) lastHeading = heading
    heading.lastId = lastHeading.id
  }
  return { blocks, sorted, bottoms, pages, headings }
}

export function readReflowPosition(index, viewport, previousPage = 1) {
  const start = upperBound(index.sorted, viewport.top, block => block.maxBottom)
  const visible = []
  for (let i = start; i < index.sorted.length && index.sorted[i].top < viewport.bottom; i++) {
    if (index.sorted[i].bottom > viewport.top) visible.push(index.sorted[i])
  }
  // Preserve DOM order for the existing dominant-page tie-breaking rule.
  visible.sort((a, b) => a.order - b.order)
  const page = dominantPage(visible, viewport, previousPage)
  const bounds = index.pages.get(page)
  const distance = bounds ? bounds.bottom - bounds.top - (viewport.bottom - viewport.top) : 0
  const progress = distance > 0 ? Math.max(0, Math.min(1, (viewport.top - bounds.top) / distance)) : 0
  const first = upperBound(index.bottoms, viewport.top, value => value)
  const heading = upperBound(index.headings, viewport.top + 100, block => block.top) - 1
  return { page, progress, blockId: index.blocks[first]?.id,
    blockOffset: index.blocks[first] ? viewport.top - index.blocks[first].top : 0,
    headingId: index.headings[heading]?.lastId }
}
