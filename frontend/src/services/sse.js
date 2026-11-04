import { request } from './http.js'

export async function streamResponse(endpoint, body, { signal, onEvent, onOpen, method = 'POST', idleTimeout = 0 } = {}) {
  const response = await request(endpoint, {
    method, headers: { 'Content-Type': 'application/json' },
    body: method === 'GET' ? undefined : JSON.stringify(body), signal,
  })
  onOpen?.(response)
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('后端未返回流式数据。')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      let timer
      let chunk
      try {
        const read = reader.read()
        chunk = idleTimeout ? await Promise.race([read, new Promise((_, reject) => {
          timer = setTimeout(() => reject(Object.assign(new Error('连接长时间未返回数据。'), { retryable: true })), idleTimeout)
        })]) : await read
      } catch (error) {
        if (error.name !== 'AbortError') error.retryable = true
        throw error
      } finally { clearTimeout(timer) }
      const { value, done } = chunk
      buffer += decoder.decode(value, { stream: !done })
      let boundary
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const data = []
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
        }
        if (!data.length) continue
        let event
        try { event = JSON.parse(data.join('\n')) }
        catch { throw new Error('收到无效的流式数据。') }
        if (['error', 'response.failed', 'response.incomplete'].includes(event.type)) {
          throw new Error(event.type === 'error' && typeof event.message === 'string'
            ? event.message : 'API 推理未完成，请重试。')
        }
        onEvent?.(event)
        if (['agent.done', 'response.completed'].includes(event.type)) return
      }
      if (done) throw Object.assign(new Error('API 流在完成之前中断，请重试。'), { retryable: true })
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
