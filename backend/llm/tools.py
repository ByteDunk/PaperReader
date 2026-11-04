"""Read-only paper tools and their model-facing schemas."""
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..papers.content import source_text
from ..resources import file_stamp


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paper_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    query: str = Field(default='', max_length=2000)
    block_id: str = Field(default='', max_length=200)
    page: int = Field(default=1, ge=1, le=100000)
    offset: int = Field(default=0, ge=0, le=1000000)
    text_offset: int = Field(default=0, ge=0, le=10000000)
    limit: int = Field(default=8, ge=1, le=20)
    all_papers: bool = False


DESCRIPTIONS = {
    'list_papers': '列出本地论文库的论文 ID、标题及索引状态。offset/limit 分页。',
    'get_outline': '获取论文目录（标题块 ID 和页码）。offset/limit 分页；无标题时可使用 read_page。',
    'read_section': '按目录中的 block_id 读取章节，直到下一个标题。offset/limit 按文本块分页。',
    'read_page': '读取指定 page 的文本与图表题注。offset/limit 按文本块分页。',
    'search_paper': '向量数据库语义检索 query；默认当前论文，all_papers=true 跨论文检索。',
    'find_text': '字面匹配 query（不区分大小写，非正则），返回精确原文。offset/limit 分页。',
    'read_context': '按 block_id 展开相邻文本块，每侧最多两块。',
    'read_block': '按 block_id 精读一个文本块，text_offset 按字符分页，每次最多 6000 字符。',
    'list_figures_tables': '列出图表题注，offset/limit 分页；不读取图片内文字。',
}
FIELDS = {
    'list_papers': ['offset', 'limit'], 'get_outline': ['paper_id', 'offset', 'limit'],
    'read_section': ['paper_id', 'block_id', 'offset', 'limit'],
    'read_page': ['paper_id', 'page', 'offset', 'limit'],
    'search_paper': ['paper_id', 'query', 'limit', 'all_papers'],
    'find_text': ['paper_id', 'query', 'offset', 'limit'],
    'read_context': ['paper_id', 'block_id'],
    'read_block': ['paper_id', 'block_id', 'text_offset'],
    'list_figures_tables': ['paper_id', 'offset', 'limit'],
}
ARGUMENT_PROPERTIES = Arguments.model_json_schema()['properties']
TOOLS = [{'type': 'function', 'name': name, 'description': description, 'strict': False,
          'parameters': {'type': 'object', 'properties': {
              key: ARGUMENT_PROPERTIES[key] for key in FIELDS[name]},
              'additionalProperties': False}}
         for name, description in DESCRIPTIONS.items()]


class PaperTools:
    def __init__(self, library, paper_id):
        self.library = library
        self.paper_id = paper_id
        self.sources = []
        self._evidence = {}
        self._document_key = None
        self._document_blocks = None

    def _blocks(self, paper_id):
        # Keep only the last document for this run. Validate its state and file
        # on every tool call so deletion, cleanup and reparse invalidate it.
        with self.library.lock:
            paper = self.library.read(paper_id)
            if paper['state'] != 'ready':
                self._document_key = self._document_blocks = None
                raise ValueError(paper.get('error') or '论文正在重排，请稍候。')
            key = (paper_id, file_stamp(self.library.directory(paper_id) / 'reflow.json'))
            if key != self._document_key:
                self._document_key = self._document_blocks = None
                blocks = self.library.reflow(paper_id)['blocks']
                self._document_key, self._document_blocks = key, blocks
            return self._document_blocks

    def evidence(self, paper_id, block, text):
        text = text[:6000]
        key = (paper_id, block['id'], text)
        if key in self._evidence:
            return self._evidence[key]
        source = {'citation': len(self.sources) + 1, 'paper_id': paper_id,
                  'paper_title': self.library.read(paper_id)['title'], 'id': block['id'],
                  'page': block['page'], 'bbox': block.get('bbox'), 'text': text}
        self.sources.append(source)
        self._evidence[key] = source
        return source

    def run(self, name, raw):
        try:
            if name not in DESCRIPTIONS:
                return {'error': '未知工具。'}
            values = json.loads(raw)
            if not isinstance(values, dict) or set(values) - set(FIELDS[name]):
                return {'error': '工具参数不符合定义。'}
            a = Arguments.model_validate(values)
            pid = a.paper_id or self.paper_id
            if name == 'list_papers':
                rows = [{k: p.get(k) for k in ('id', 'title', 'state', 'index')}
                        for p in self.library.list()]
            elif name == 'search_paper':
                if not a.query.strip():
                    return {'error': 'query 不能为空。'}
                result = self.library.rag.search(a.query, 'all' if a.all_papers else 'paper', pid, a.limit)
                rows = [self.evidence(r['paper_id'], {'id': r['block_id'], 'page': r['page'],
                         'bbox': r.get('bbox')}, r['text']) for r in result['results']]
                return {**result, 'results': rows}
            else:
                blocks = self._blocks(pid)
                if name == 'get_outline':
                    rows = [{'block_id': b['id'], 'title': source_text(b), 'page': b['page']}
                            for b in blocks if b['type'] in ('heading', 'title')]
                else:
                    if name in ('read_section', 'read_context', 'read_block'):
                        start = next((i for i, b in enumerate(blocks) if b['id'] == a.block_id), None)
                        if start is None:
                            return {'error': '未找到该文本块，请先获取目录或检索。'}
                        if name == 'read_block':
                            block = blocks[start]
                            text = source_text(block)
                            end = a.text_offset + 6000
                            return {'results': [self.evidence(pid, block, text[a.text_offset:end])],
                                    'next_text_offset': end if end < len(text) else None}
                        if name == 'read_context':
                            blocks = blocks[max(0, start - 2):start + 3]
                        else:
                            end = next((i for i in range(start + 1, len(blocks))
                                        if blocks[i]['type'] in ('heading', 'title')), len(blocks))
                            blocks = blocks[start:end]
                    elif name == 'read_page':
                        blocks = [b for b in blocks if b['page'] == a.page]
                    elif name == 'find_text':
                        if not a.query.strip():
                            return {'error': 'query 不能为空。'}
                        blocks = [b for b in blocks if a.query.casefold() in source_text(b).casefold()]
                    elif name == 'list_figures_tables':
                        blocks = [b for b in blocks if b['type'] in ('figure', 'table')]
                    rows = blocks
                    total = len(rows)
                    selected = rows[a.offset:a.offset + a.limit]
                    evidence = []
                    for b in selected:
                        text = source_text(b)
                        start = max(0, text.casefold().find(a.query.casefold()) - 500) if name == 'find_text' else 0
                        evidence.append({**self.evidence(pid, b, text[start:start + 6000]),
                                         'text_offset': start, 'truncated': start > 0 or len(text) > start + 6000})
                    return {'results': evidence, 'total': total,
                            'text_limit': 6000, 'next_offset': a.offset + a.limit if a.offset + a.limit < total else None}
            return {'results': rows[a.offset:a.offset + a.limit], 'total': len(rows),
                    'next_offset': a.offset + a.limit if a.offset + a.limit < len(rows) else None}
        except (ValidationError, ValueError, TypeError):
            return {'error': '参数无效或论文/索引尚未就绪，请检查参数，或改用其他阅读工具。'}
        except FileNotFoundError:
            return {'error': '论文不存在或已经删除。'}
        except RuntimeError:
            return {'error': '检索暂不可用，请改用目录、章节或文本匹配。'}
