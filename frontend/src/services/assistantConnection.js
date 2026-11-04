import { streamResponse } from './sse.js'
import { apiFetch } from './desktop.js'

const MAX_RETRIES = 5

function waitForReconnect(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError')) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', aborted); resolve() }, milliseconds)
    if (signal?.aborted) aborted()
    else signal?.addEventListener('abort', aborted, { once: true })
  })
}

export async function stopAssistantRun(requestId) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 5000)
  try { await apiFetch(`/api/assistant/runs/${encodeURIComponent(requestId)}`, { method: 'DELETE', keepalive: true, signal: controller.signal }) }
  catch { /* The server's disconnect grace period also stops orphaned runs. */ }
  finally { clearTimeout(timer) }
}

export async function streamAssistant(body, { signal, onEvent }) {
  const requestId = body.request_id
  let sequence = 0
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (signal?.aborted) throw new DOMException('Stopped', 'AbortError')
    const connection = new AbortController()
    const aborted = () => connection.abort()
    signal?.addEventListener('abort', aborted, { once: true })
    let timedOut = false
    let headerTimer = setTimeout(() => { timedOut = true; connection.abort() }, 30000)
    try {
      const endpoint = sequence ? `/api/assistant/runs/${encodeURIComponent(requestId)}/events?after=${sequence}` : '/api/assistant/chat'
      return await streamResponse(endpoint, body, {
        method: sequence ? 'GET' : 'POST', signal: connection.signal, idleTimeout: 45000,
        onOpen() { clearTimeout(headerTimer) },
        onEvent(event) {
          const next = event.sequence
          if (Number.isInteger(next) && next <= sequence) return
          onEvent(event)
          if (Number.isInteger(next)) sequence = next
        },
      })
    } catch (error) {
      if (signal?.aborted) { await stopAssistantRun(requestId); throw new DOMException('Stopped', 'AbortError') }
      if (timedOut) error = Object.assign(new Error('连接后端超时。'), { retryable: true })
      if (!error.retryable || attempt === MAX_RETRIES) { await stopAssistantRun(requestId); throw error }
      onEvent({ type: 'agent.connection', attempt: attempt + 1, max_retries: MAX_RETRIES,
        message: `连接中断，正在重新连接（${attempt + 1}/${MAX_RETRIES}）…` })
      try { await waitForReconnect(Math.min(1000 * 2 ** attempt, 16000), signal) }
      catch (error) { await stopAssistantRun(requestId); throw error }
    } finally {
      clearTimeout(headerTimer)
      signal?.removeEventListener('abort', aborted)
    }
  }
}
