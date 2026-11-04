// Preserve cancellation and expose consistent backend errors to every service.
import { apiFetch } from './desktop.js'

export async function requestJson(path, options, errorLabel) {
  const response = await request(path, { cache: 'no-store', ...options }, errorLabel)
  return response.status === 204 ? null : response.json()
}

export async function request(path, options, errorLabel = '请求失败') {
  let response
  try { response = await apiFetch(path, options) }
  catch (error) {
    if (error.name === 'AbortError') throw error
    throw Object.assign(new Error('暂时无法连接应用服务，请稍后重试。'), { retryable: true })
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw Object.assign(new Error(typeof body.detail === 'string' ? body.detail : `${errorLabel}（${response.status}）`),
      { status: response.status, retryable: [408, 425, 429].includes(response.status) || response.status >= 500 })
  }
  return response
}

export function paperApi(path = '', options) {
  return requestJson(`/api/papers${path}`, options)
}
