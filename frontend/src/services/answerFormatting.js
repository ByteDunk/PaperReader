function fence(line) {
  const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line)
  return match ? { marker: match[1][0], length: match[1].length, suffix: match[2] } : null
}

function closesFence(open, candidate) {
  return candidate && candidate.marker === open.marker && candidate.length >= open.length && !candidate.suffix.trim()
}

// Display citations by first use; tool records retain their evidence IDs.
export function presentAnswer(text = '', sources = []) {
  const known = new Map(sources.map(source => [source.citation, source]))
  const used = new Map()
  let open = null
  const lines = text.split(/\r?\n/).map(line => {
    const candidate = fence(line)
    if (open) {
      if (closesFence(open, candidate)) open = null
      return line
    }
    if (candidate) { open = candidate; return line }
    return line.replace(/(`[^`]*`)|\[(\d+)\]/g, (match, code, number) => {
      if (code || !known.has(Number(number))) return match
      const citation = Number(number)
      if (!used.has(citation)) used.set(citation, used.size + 1)
      return `[${used.get(citation)}]`
    })
  })
  return { text: lines.join('\n'), citationNumbers: used,
    sources: [...used].map(([citation, number]) => ({ ...known.get(citation), citation: number })) }
}

export function answerBlocks(text = '') {
  const blocks = []
  let paragraph = []
  let code = []
  let open = null
  const flush = () => {
    if (paragraph.length) blocks.push({ type: 'paragraph', text: paragraph.join('\n') })
    paragraph = []
  }
  for (const line of text.split(/\r?\n/)) {
    const candidate = fence(line)
    if (open) {
      if (closesFence(open, candidate)) {
        blocks.push({ type: 'code', text: code.join('\n') })
        code = []
        open = null
      } else code.push(line)
      continue
    }
    if (candidate) { flush(); open = candidate; continue }
    const heading = /^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)/.exec(line)
    if (heading) {
      flush()
      blocks.push({ type: 'heading', level: heading[1].length,
        text: (heading[2] || '').replace(/[ \t]+#+[ \t]*$/, '').trim() })
    } else if (!line.trim()) flush()
    else paragraph.push(line)
  }
  flush()
  if (open) blocks.push({ type: 'code', text: code.join('\n') })
  return blocks
}
