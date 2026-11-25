"""Index published parser blocks while translation continues."""
import hashlib
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import deque

from .embedding import LocalEmbedding
from .store import IndexStore

from ..papers.content import source_text
from ..parse.pdf import PARSER_VERSION

logger = logging.getLogger(__name__)


class IndexNotReady(ValueError):
    pass


class RagService:
    def __init__(self, library, embedding=None):
        self.library = library
        self.embedding = embedding if embedding is not None else LocalEmbedding()
        self.store = IndexStore(library.root / 'rag.sqlite3')
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rag-index')
        self.documents = {}
        self.closing = False
        self.options = library.options

    def signature(self, paper):
        version = paper.get('parser_version', PARSER_VERSION)
        return hashlib.sha256(f'{version}:{self.embedding.signature}'.encode()).hexdigest()

    def _current(self, paper_id, revision):
        doc = self.documents.get(paper_id)
        return doc if doc and doc['revision'] == revision and not self.closing else None

    def _save(self, paper_id, doc, force=True):
        now = time.monotonic()
        if not force and now - doc.get('last_save', 0) < .5:
            return
        paper = self.library.read(paper_id)
        progress = round(doc['processed'] / max(1, doc['total']) * 99)
        if doc['state'] == 'ready':
            progress = 100
        paper['index'] = {'state': doc['state'], 'progress': progress,
                          'completed': doc['processed'], 'total': doc['total'],
                          'chunks': doc['chunks'], 'source_complete': True,
                          'error': doc['error'], 'revision': doc['revision'], 'signature': doc['signature']}
        self.library.save(paper)
        doc['last_save'] = now

    def reconcile(self, paper_ids):
        self.store.reconcile(paper_ids)

    def restore_ready(self, paper_id, force=False):
        with self.library.lock:
            paper = self.library.read(paper_id)
            if not force and paper.get('index', {}).get('state') == 'ready' and self.store.current(paper_id, self.signature(paper)):
                return
            blocks = deque({key: block[key] for key in ('id', 'type', 'page', 'bbox', 'sources')}
                           | {'text': source_text(block)} for block in self.library.reflow(paper_id)['blocks'])
            revision, signature = uuid.uuid4().hex, self.signature(paper)
            doc = {'revision': revision, 'signature': signature, 'blocks': blocks, 'total': len(blocks),
                   'scheduled': False, 'processed': 0, 'chunks': 0, 'state': 'indexing', 'error': '',
                   'section': '', 'document_id': self.store.start(paper_id, revision, signature)}
            self.documents[paper_id] = doc
            self._save(paper_id, doc)
            self._schedule(paper_id, doc)

    def _chunks(self, doc, blocks):
        chunks = []
        section = doc['section']
        for block in blocks:
            if block['type'] in ('heading', 'title'):
                section = block['text'][:300]
            text = block['text']
            if not text:
                continue
            prefix = f'Section: {section}\n' if section and block['type'] not in ('heading', 'title') else ''
            for chunk in self.embedding.split(text, prefix):
                chunks.append({**chunk, 'block_id': block['id'], 'page': block['page'],
                               'bbox': block['bbox'], 'sources': block['sources'],
                               'section': section})
        return chunks, section

    def configure(self, options):
        self.options = options
        self.embedding.configure(options)

    def maintain(self):
        self.embedding.release_idle()
        self.store.compact()

    def clear_cache(self, full=False):
        if full:
            self.executor.submit(lambda: None).result()
        self.embedding.close()
        if full:
            self.store.reset()

    def _schedule(self, paper_id, doc):
        if not self.closing and not doc['scheduled']:
            doc['scheduled'] = True
            self.executor.submit(self._run, paper_id, doc['revision'])

    def _run(self, paper_id, revision):
        try:
            with self.library.lock:
                doc = self._current(paper_id, revision)
                if not doc:
                    return
                blocks = [doc['blocks'].popleft() for _ in range(min(8, len(doc['blocks'])))]
                if not blocks:
                    if not doc['chunks']:
                        raise RuntimeError('论文没有可索引的文字内容。')
                    self.store.publish(doc['document_id'])
                    doc['state'] = 'ready'
                    self._save(paper_id, doc)
                    self.documents.pop(paper_id, None)
                    return
            chunks, section = self._chunks(doc, blocks)
            batch_size = self.options['index_batch_size']
            for offset in range(0, len(chunks), batch_size):
                with self.library.lock:
                    if not self._current(paper_id, revision):
                        return
                batch = chunks[offset:offset + batch_size]
                vectors = self.embedding.encode([chunk['text'] for chunk in batch])
                with self.library.lock:
                    doc = self._current(paper_id, revision)
                    if not doc:
                        return
                    self.store.append(doc['document_id'], batch, vectors)
                    doc['chunks'] += len(batch)
            with self.library.lock:
                doc = self._current(paper_id, revision)
                if doc:
                    doc['processed'] += len(blocks)
                    doc['section'] = section
                    self._save(paper_id, doc, force=False)
        except Exception as exc:
            logger.exception('RAG indexing failed: %s', paper_id)
            with self.library.lock:
                doc = self._current(paper_id, revision)
                if doc:
                    doc.update(state='failed', error=str(exc) if isinstance(exc, RuntimeError) else '索引失败，请重新构建索引。')
                    doc['blocks'].clear()
                    self._save(paper_id, doc)
                    self.documents.pop(paper_id, None)
        finally:
            with self.library.lock:
                doc = self._current(paper_id, revision)
                if doc:
                    doc['scheduled'] = False
                    if doc['state'] == 'indexing':
                        self._schedule(paper_id, doc)

    def remove(self, paper_id):
        with self.library.lock:
            self.documents.pop(paper_id, None)
            self.store.remove(paper_id)

    def search(self, query, scope, paper_id=None, limit=12):
        with self.library.lock:
            if scope == 'paper':
                paper = self.library.read(paper_id)
                ready = self.store.current(paper_id, self.signature(paper))
                if paper.get('index', {}).get('state') != 'ready' or not ready:
                    raise IndexNotReady(paper.get('index', {}).get('error') or '当前论文索引尚未完成，请稍候。')
            else:
                ready = None
            if scope != 'paper' and not any(p.get('index', {}).get('state') == 'ready' for p in self.library.list()):
                raise IndexNotReady('暂无已完成的论文索引，请等待索引构建。')
        vector = self.embedding.encode([query], query=True)[0]
        with self.library.lock:
            papers = {paper['id']: paper for paper in self.library.list()}
            if scope == 'paper':
                paper = papers.get(paper_id)
                current = paper and self.store.current(paper_id, self.signature(paper))
                if not current or current['revision'] != ready['revision']:
                    raise IndexNotReady('论文索引已改变，请重新搜索。')
            results = self.store.search(query, vector, ready['id'] if ready else None, limit)
            results = [{**item, 'paper_title': papers[item['paper_id']]['title']}
                       for item in results if papers.get(item['paper_id'], {}).get('index', {}).get('state') == 'ready']
            pending = sum(p.get('index', {}).get('state') != 'ready' for p in papers.values())
            return {'results': results, 'scope': scope, 'query': query,
                    'indexed_papers': len(papers) - pending, 'pending_papers': pending if scope == 'all' else 0}

    def retry(self, paper_id):
        with self.library.lock:
            paper = self.library.read(paper_id)
            if paper['state'] != 'ready':
                raise IndexNotReady('请等待论文解析完成。')
            current = self.documents.get(paper_id)
            if current and current['state'] == 'indexing':
                return paper
            self.restore_ready(paper_id, force=True)
            return self.library.read(paper_id)

    def shutdown(self):
        with self.library.lock:
            self.closing = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.documents.clear()
        self.embedding.close()
        self.store.compact(force=True)
