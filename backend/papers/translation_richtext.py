"""Carry bold ranges through translation without rendering model-provided HTML."""
import re
import uuid

from ..llm.client import LLMError


def hide_partial_marker(text, prefix):
    """Keep incomplete protocol markers out of streamed display text."""
    tail = text.rfind('[[')
    if tail >= 0 and ']]' not in text[tail:]:
        fragment = text[tail + 2:].lstrip('/')
        if prefix.startswith(fragment) or fragment.startswith(prefix):
            return text[:tail]
    return text[:-1] if text.endswith('[') else text


class TranslationText:
    def __init__(self, block):
        self.source = block['src']
        spans = block.get('caption_spans' if block['type'] in ('figure', 'table') else 'spans') or []
        self.ranges = []
        if ''.join(s.get('text', '') for s in spans).strip() == self.source:
            for span in spans:
                text, bold = span.get('text', ''), bool(span.get('bold'))
                if not text:
                    continue
                if (self.ranges and self.ranges[-1]['bold'] == bold
                        and not span.get('asset') and not self.ranges[-1].get('asset')):
                    self.ranges[-1]['text'] += text
                else:
                    self.ranges.append({**span, 'text': text, 'bold': bold})
        self.count = sum(s['bold'] and bool(s['text'].strip()) and not s.get('asset') for s in self.ranges)
        self.all_bold = bool(self.count) and all(s['bold'] or not s['text'].strip() for s in self.ranges)
        self.prefix = 'b' + uuid.uuid4().hex[:12]
        self.pattern = re.compile(r'\[\[(/?)' + self.prefix + r':(\d+)\]\]')
        self.formula_prefix = 'f' + uuid.uuid4().hex[:12]
        self.formula_pattern = re.compile(r'\[\[' + self.formula_prefix + r':(\d+)\]\]')
        self.formulas = []
        self.input = self.source
        self.instructions = ''
        if self.count or any(s.get('asset') for s in self.ranges):
            chunks, index = [], 0
            for span in self.ranges:
                if span.get('asset'):
                    chunks.append(f'[[{self.formula_prefix}:{len(self.formulas)}]]')
                    self.formulas.append(span)
                elif span['bold'] and span['text'].strip():
                    chunks.append(f'[[{self.prefix}:{index}]]{span["text"]}[[/{self.prefix}:{index}]]')
                    index += 1
                else:
                    chunks.append(span['text'])
            self.input = ''.join(chunks).strip()
            self.instructions = (
                f'输入中的 [[{self.prefix}:编号]] 和 [[/{self.prefix}:编号]] 是粗体起止标记。'
                '请完整翻译整个段落，将每一对标记保留在对应的译文词句两侧，'
                '每对恰好出现一次，允许随译文语序移动；不要翻译标记、嵌套标记或添加其他格式。'
            ) if self.count else ''
            if self.formulas:
                self.instructions += (f' [[{self.formula_prefix}:编号]] 代表原文行内公式，'
                                      '每个标记须原样保留一次，允许随语序移动，不翻译或展开标记。')

    def decode(self, text, final=False):
        if not self.formulas:
            return self._decode_bold(text, final)
        if not final:
            text = hide_partial_marker(text, self.formula_prefix)
        _, decoded = self._decode_bold(text, final)
        spans, seen = [], []
        for span in decoded:
            cursor = 0
            for match in self.formula_pattern.finditer(span['text']):
                index = int(match[1])
                if index >= len(self.formulas):
                    raise LLMError('模型返回了无效的行内公式标记，请重试该段落。')
                if match.start() > cursor:
                    spans.append({**span, 'text': span['text'][cursor:match.start()]})
                spans.append({**self.formulas[index], 'bold': span['bold']})
                seen.append(index)
                cursor = match.end()
            if cursor < len(span['text']):
                spans.append({**span, 'text': span['text'][cursor:]})
        plain = ''.join(s['text'] for s in spans)
        if final and (sorted(seen) != list(range(len(self.formulas))) or self.formula_prefix in plain):
            raise LLMError('模型未完整保留原文行内公式标记，请重试该段落。')
        return plain, spans

    def _decode_bold(self, text, final=False):
        if not self.count:
            return text, [{'text': text, 'bold': False}] if text else []
        # A streaming chunk may end halfway through a marker; don't expose it.
        if not final:
            text = hide_partial_marker(text, self.prefix)
        spans, cursor, active, seen, valid = [], 0, None, set(), True
        for match in self.pattern.finditer(text):
            if match.start() > cursor:
                spans.append({'text': text[cursor:match.start()], 'bold': active is not None})
            closing, index = bool(match[1]), int(match[2])
            if closing:
                if active != index:
                    valid = False
                active = None
            else:
                if active is not None or index in seen or index >= self.count:
                    valid = False
                active = index
                seen.add(index)
            cursor = match.end()
        if cursor < len(text):
            spans.append({'text': text[cursor:], 'bold': active is not None})
        plain = ''.join(s['text'] for s in spans)
        if final:
            if not seen and self.all_bold and self.prefix not in plain:
                spans = [{'text': plain, 'bold': True}]
            elif not valid or active is not None or seen != set(range(self.count)) or self.prefix in plain:
                raise LLMError('模型未完整保留原文粗体标记，请重试该段落。')
        return plain, spans


class TranslationBatch:
    def __init__(self, blocks):
        self.blocks = blocks
        self.rich = [TranslationText(block) for block in blocks]
        self.instructions = ''.join(item.instructions for item in self.rich)
        self.prefix = 't' + uuid.uuid4().hex
        self.pattern = re.compile(r'\[\[(/?)' + self.prefix + r':(\d+)\]\]')
        if len(blocks) == 1:
            self.input = self.rich[0].input
        else:
            self.input = '\n\n'.join(f'[[{self.prefix}:{i}]]\n{item.input}\n[[/{self.prefix}:{i}]]'
                                      for i, item in enumerate(self.rich))
            self.instructions += (
                f'本次包含 {len(blocks)} 个独立内容块，块边界为 [[{self.prefix}:编号]] '
                f'和 [[/{self.prefix}:编号]]。分别翻译每个块，保留全部块边界标记，'
                '每个编号恰好出现一对；译文放在对应编号内部，不合并、遗漏或交换内容，'
                '不在块外输出任何内容。块内的粗体和公式标记仍须原样保留。'
            )

    def decode(self, text, final=False):
        if len(self.blocks) == 1:
            return {self.blocks[0]['id']: self.rich[0].decode(text, final)}
        # Hide a boundary marker split across SSE events, including a lone '['.
        if not final:
            text = hide_partial_marker(text, self.prefix)
        active, cursor = None, 0
        seen, closed, values = set(), set(), {}

        def append(fragment):
            if active is not None:
                values[active] += fragment
            elif fragment.strip():
                raise LLMError('模型未按内容块返回译文，请重试。')

        for marker in self.pattern.finditer(text):
            append(text[cursor:marker.start()])
            index = int(marker[2])
            if index >= len(self.blocks):
                raise LLMError('模型返回了未知内容块，请重试。')
            if marker[1]:
                if active != index:
                    raise LLMError('模型返回的内容块边界不匹配，请重试。')
                closed.add(index)
                active = None
            else:
                if active is not None or index in seen:
                    raise LLMError('模型返回了重复或嵌套的内容块，请重试。')
                active = index
                seen.add(index)
                values[index] = ''
            cursor = marker.end()
        append(text[cursor:])
        if final and (active is not None or closed != set(range(len(self.blocks)))):
            raise LLMError('模型未完整返回全部内容块，请重试。')
        result = {}
        for index, value in values.items():
            plain, spans = self.rich[index].decode(value.strip(), final)
            if final and not plain.strip():
                raise LLMError('模型返回了空白内容块译文，请重试。')
            result[self.blocks[index]['id']] = plain, spans
        return result
