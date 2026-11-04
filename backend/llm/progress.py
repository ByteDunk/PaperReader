"""Separate ordinary model output from provisional and validated answers."""
import json
import re


def partial_answer(arguments):
    """Decode complete JSON string tokens, withholding split escapes/surrogates."""
    start = re.match(r'^\s*\{\s*"answer"\s*:\s*"', arguments)
    if not start:
        return ''
    tokens = re.match(r'(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*', arguments[start.end():])[0]
    text = json.loads('"' + tokens + '"')
    if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
        text = text[:-1]
    return text.encode('utf-8', errors='replace').decode('utf-8')[:30000]


class RoundProgress:
    def __init__(self, turn, attempt=0):
        self.turn = turn
        self.output_id = f'{turn}:output' + (f':retry{attempt}' if attempt else '')
        self.output = ''
        self.names = {}
        self.arguments = {}
        self.preview = ''

    def update(self, event):
        kind = event['type']
        key = str(event.get('item_id', event.get('output_index', '0')))
        if kind in ('response.output_text.delta', 'response.refusal.delta'):
            delta = event.get('delta', '')
            if not isinstance(delta, str) or not delta:
                return []
            self.output += delta
            return [{'type': 'agent.progress', 'id': self.output_id,
                     'round': self.turn, 'delta': delta, 'done': False}]
        if kind in ('response.output_item.added', 'response.output_item.done'):
            item = event.get('item', {})
            if item.get('type') == 'function_call':
                key = str(item.get('id', event.get('output_index', '0')))
                self.names[key] = item.get('name', '')
                self.arguments[key] = item.get('arguments', '')
        elif kind == 'response.function_call_arguments.delta':
            if event.get('name'):
                self.names[key] = event['name']
            self.arguments[key] = self.arguments.get(key, '') + event.get('delta', '')
        elif kind == 'response.completed':
            # Reconcile streamed text and support providers returning only a final
            # snapshot. The same ID prevents the UI from duplicating the output.
            output = event.get('response', {}).get('output', [])
            text = ''.join(p.get('text', '') if p.get('type') == 'output_text' else p.get('refusal', '')
                           for item in output if item.get('type') == 'message'
                           for p in item.get('content', []) if p.get('type') in ('output_text', 'refusal'))
            self.output = text or self.output
            return ([{'type': 'agent.progress', 'id': self.output_id, 'round': self.turn,
                      'text': self.output, 'done': True}] if self.output else [])
        if self.names.get(key) == 'finish_answer':
            text = partial_answer(self.arguments.get(key, ''))
            if text and text != self.preview:
                self.preview = text
                return [{'type': 'agent.answer', 'text': text}]
        return []
