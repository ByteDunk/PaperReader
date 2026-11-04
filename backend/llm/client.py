"""Responses/SSE transport for translation, connection tests and the assistant."""
import json
from contextlib import aclosing

import anyio
import httpx


class LLMError(Exception):
    def __init__(self, message, status=502, upstream_status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.upstream_status = upstream_status
        self.retryable = retryable or upstream_status == 0 or upstream_status in (408, 429) or (
            upstream_status is not None and upstream_status >= 500)


def sse_event(data):
    name = data.get('type', 'message')
    return f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def transient_stream_error(event):
    response = event.get('response')
    error = event.get('error') or (response.get('error') if isinstance(response, dict) else None) or {}
    return isinstance(error, dict) and error.get('code', error.get('type')) in (
        'server_error', 'rate_limit_exceeded', 'timeout', 'request_timeout', 'overloaded', 'overloaded_error')


def stream_error_message(event):
    response = event.get('response')
    error = event.get('error') or (response.get('error') if isinstance(response, dict) else None) or {}
    if isinstance(error, dict):
        message = str(error.get('message', '')).lower()
        if 'tool_choice' in message and 'thinking mode' in message:
            return '该模型的思考模式不支持强制工具选择，请使用自动工具选择。'
    return 'API 推理失败，请检查模型权限、额度及输入。'


async def read_events(response):
    """Decode SSE without assuming network chunks are complete events."""
    lines = []
    name = ''
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if lines:
                data = '\n'.join(lines)
                if data == '[DONE]':
                    return
                try:
                    event = json.loads(data)
                except ValueError as exc:
                    raise LLMError('API 返回了无效的流式数据。') from exc
                if not isinstance(event, dict):
                    raise LLMError('API 返回了无效的流式事件。')
                event.setdefault('type', name or 'message')
                yield event
            lines, name, size = [], '', 0
        elif line.startswith('data:'):
            lines.append(line[5:].lstrip(' '))
            size += len(line)
            if size > 8 * 1024 * 1024:
                raise LLMError('API 返回的单个流式事件过大。')
        elif line.startswith('event:'):
            name = line[6:].strip()
    if lines:
        # A terminal event without the mandatory SSE blank line is incomplete.
        raise LLMError('API 流式事件未完整返回。', retryable=True)


async def relay_events(response, api_key, events):
    """Encode either provider's events with the same errors and resource lifetime."""
    try:
        async for event in events:
            kind = event.get('type')
            if kind in ('error', 'response.failed'):
                raise LLMError(stream_error_message(event), retryable=transient_stream_error(event))
            if kind == 'response.incomplete':
                raise LLMError('API 输出未完成，可能达到输出长度限制。')
            # Protect against credentials echoed by a misconfigured upstream.
            yield sse_event(event).replace(api_key, '[REDACTED]')
            if kind == 'response.completed':
                return
        raise LLMError('API 流在完成事件之前中断，请重试。', retryable=True)
    except httpx.TimeoutException:
        yield sse_event({'type': 'error', 'message': '等待 API 流式响应超时，请重试。', 'retryable': True})
    except httpx.HTTPError:
        yield sse_event({'type': 'error', 'message': 'API 流式连接中断，请重试。', 'retryable': True})
    except LLMError as exc:
        yield sse_event({'type': 'error', 'message': str(exc), 'retryable': exc.retryable})
    finally:
        # Disconnects cancel streaming tasks; upstream cleanup must still finish.
        with anyio.CancelScope(shield=True):
            try:
                await events.aclose()
            finally:
                await response.aclose()


class ResponsesClient:
    def __init__(self):
        self.http = None

    async def open(self, settings, payload, *, read_timeout=120, endpoint='/responses'):
        if not settings['api_key']:
            raise LLMError('请先在 API 设置中填写并保存 API Key。', 400)
        if self.http is None:
            self.http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15),
                                          limits=httpx.Limits(max_connections=32, max_keepalive_connections=30),
                                          follow_redirects=False)
        client = self.http
        body = {**payload, 'model': settings['model'], 'stream': True}
        request = client.build_request('POST', settings['base_url'] + endpoint, json=body,
                                       timeout=httpx.Timeout(read_timeout, connect=15),
                                       headers={'Authorization': 'Bearer ' + settings['api_key'],
                                                'Accept': 'text/event-stream'})
        try:
            response = await client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise LLMError('连接 API 超时，请检查网络和 API 地址。', 504, upstream_status=0) from exc
        except httpx.HTTPError as exc:
            raise LLMError('无法连接 API，请检查网络和 API 地址。', upstream_status=0) from exc
        if response.status_code != 200:
            status = response.status_code
            await response.aclose()
            messages = {401: 'API Key 无效或已过期。', 403: 'API 无访问权限，请检查密钥和模型权限。',
                        404: 'API 地址或模型不存在，请检查设置。', 429: 'API 请求限流或额度不足，请稍后重试。'}
            raise LLMError(messages.get(status, f'API 请求失败（HTTP {status}）。'), upstream_status=status)
        if 'text/event-stream' not in response.headers.get('content-type', '').lower():
            await response.aclose()
            raise LLMError('API 未返回 SSE 流，请确认该地址支持请求的流式接口。')
        return response

    def stream(self, response, api_key):
        return relay_events(response, api_key, read_events(response))

    async def complete_text(self, settings, payload, on_text):
        """Consume the same Responses stream for persistent background work."""
        response = await self.open(settings, payload)
        text = ''
        stream = self.stream(response, settings['api_key'])
        async with aclosing(stream):
            async for frame in stream:
                event = json.loads(frame.split('\ndata: ', 1)[1])
                kind = event.get('type')
                if kind == 'error':
                    raise LLMError(event['message'])
                if kind == 'response.output_text.delta':
                    text += event.get('delta', '')
                    on_text(text)
                if kind == 'response.completed':
                    final = ''.join(part.get('text', '')
                                    for item in event.get('response', {}).get('output', []) if item.get('type') == 'message'
                                    for part in item.get('content', []) if part.get('type') == 'output_text')
                    text = final or text
                    if not text.strip():
                        raise LLMError('API 未返回有效译文，请重试。')
                    return text.strip()
            raise LLMError('API 翻译未完成，请重试。')

    async def shutdown(self):
        if self.http is not None:
            await self.http.aclose()
            self.http = None
