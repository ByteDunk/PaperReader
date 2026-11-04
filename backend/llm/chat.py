"""Tool-call adapter for gateways whose Responses endpoint only returns text."""
from .client import LLMError, read_events, relay_events, transient_stream_error, stream_error_message


def chat_payload(payload):
    messages = [{'role': 'system', 'content': payload['instructions']}]
    for item in payload['input']:
        kind = item.get('type', 'message')
        if kind == 'function_call':
            if messages[-1]['role'] != 'assistant':
                messages.append({'role': 'assistant', 'content': None})
            messages[-1].setdefault('tool_calls', []).append({
                'id': item['call_id'], 'type': 'function',
                'function': {'name': item['name'], 'arguments': item['arguments']}})
        elif kind == 'function_call_output':
            messages.append({'role': 'tool', 'tool_call_id': item['call_id'], 'content': item['output']})
        elif kind == 'message':
            content = item.get('content', '')
            if isinstance(content, list):
                content = ''.join(part.get('text', '') for part in content if part.get('type') == 'output_text')
            role = item.get('role', 'assistant')
            message = {'role': 'system' if role == 'developer' else role, 'content': content}
            if 'reasoning_content' in item:
                message['reasoning_content'] = item['reasoning_content']
            messages.append(message)
    choice = payload['tool_choice']
    if isinstance(choice, dict):
        choice = {'type': 'function', 'function': {'name': choice['name']}}
    return {'messages': messages, 'tools': [
        {'type': 'function', 'function': {k: v for k, v in tool.items() if k != 'type'}}
        for tool in payload['tools']], 'tool_choice': choice, 'max_tokens': payload['max_output_tokens']}


def chat_stream(response, api_key):
    return relay_events(response, api_key, chat_events(response))


async def chat_events(response):
    """Reassemble split tool arguments and emit the agent's internal event format."""
    text, reasoning, calls = '', '', {}
    size = 0
    async for event in read_events(response):
        if 'error' in event:
            raise LLMError(stream_error_message(event),
                           retryable=transient_stream_error(event))
        for choice in event.get('choices', []):
            if choice.get('index', 0) != 0:
                continue
            delta = choice.get('delta') or {}
            content = delta.get('content') or ''
            thought = delta.get('reasoning_content') or ''
            text += content
            reasoning += thought
            size += len(content) + len(thought)
            if thought:
                # Reasoning is retained for upstream continuation, not the UI.
                yield {'type': 'response.reasoning_text.delta'}
            if content:
                yield {'type': 'response.output_text.delta', 'delta': content}
            for part in delta.get('tool_calls') or []:
                index = part['index']
                if not isinstance(index, int) or not 0 <= index < 8:
                    raise LLMError('模型超出工具调用上限，请缩小问题范围后重试。')
                call = calls.setdefault(index, {'type': 'function_call', 'call_id': '', 'name': '', 'arguments': ''})
                if part.get('id'):
                    call['call_id'] = part['id']
                function = part.get('function') or {}
                call['name'] += function.get('name') or ''
                arguments = function.get('arguments') or ''
                call['arguments'] += arguments
                size += len(arguments)
                yield {'type': 'response.function_call_arguments.delta',
                       'item_id': str(index), 'name': call['name'], 'delta': arguments}
            if size > 8 * 1024 * 1024:
                raise LLMError('API 返回的模型输出过大。')
            finish = choice.get('finish_reason')
            if finish:
                if finish not in ('stop', 'tool_calls'):
                    raise LLMError('API 输出未完成，可能达到输出长度限制或被服务拒绝。')
                if any(not c['call_id'] or not c['name'] for c in calls.values()):
                    raise LLMError('API 返回了不完整的工具调用。')
                message = {'type': 'message', 'role': 'assistant',
                           'content': [{'type': 'output_text', 'text': text}]}
                if reasoning:
                    # Preserve the API-provided reasoning for tool continuation.
                    message['reasoning_content'] = reasoning
                output = [message, *(calls[i] for i in sorted(calls))]
                yield {'type': 'response.completed', 'response': {'output': output}}
                return
