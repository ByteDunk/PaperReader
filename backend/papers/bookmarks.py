"""User bookmarks are paper data, independent of parsing and search caches."""
from datetime import datetime, timezone
from uuid import uuid4

from ..resources import read_json, write_json


class Bookmarks:
    def __init__(self, library):
        self.library = library

    def _read(self, paper_id):
        self.library.read(paper_id)
        path = self.library.directory(paper_id) / 'bookmarks.json'
        return read_json(path) if path.exists() else []

    def _present(self, bookmark, paper):
        return {**bookmark, 'paper_id': paper['id'], 'paper_title': paper['title']}

    def list(self, paper_id=None):
        with self.library.lock:
            papers = [self.library.read(paper_id)] if paper_id else self.library.list()
            result = [self._present(bookmark, paper) for paper in papers
                      for bookmark in self._read(paper['id'])]
            return sorted(result, key=lambda item: (item['pinned'], item['created_at'], item['id']), reverse=True)

    def add(self, paper_id, block_id, note):
        with self.library.file_locks.hold(paper_id), self.library.lock:
            paper = self.library.read(paper_id)
            if paper_id in self.library.deleting:
                raise FileNotFoundError('论文不存在。')
            bookmarks = self._read(paper_id)
            existing = next((item for item in bookmarks if item['block_id'] == block_id), None)
            if existing:
                return self._present(existing, paper)
            if paper['state'] != 'ready':
                raise ValueError('请等待论文重排完成后添加书签。')
            document = self.library.reflow(paper_id)
            block = next((item for item in document['blocks'] if item['id'] == block_id), None)
            if block is None:
                raise FileNotFoundError('论文段落不存在，请刷新后重试。')
            text = block.get('text') or block.get('caption') or (
                '论文公式' if block.get('type') == 'equation' else '论文图表' if block.get('asset') else '论文片段')
            bookmark = {'id': uuid4().hex, 'block_id': block_id, 'page': block['page'],
                        'bbox': block.get('bbox'), 'text': text, 'note': note.strip() or text, 'pinned': False,
                        'created_at': datetime.now(timezone.utc).isoformat()}
            write_json(self.library.directory(paper_id) / 'bookmarks.json', [*bookmarks, bookmark])
            return self._present(bookmark, paper)

    def update(self, paper_id, bookmark_id, changes):
        with self.library.file_locks.hold(paper_id), self.library.lock:
            bookmarks = self._read(paper_id)
            bookmark = next((item for item in bookmarks if item['id'] == bookmark_id), None)
            if bookmark is None:
                raise FileNotFoundError('书签不存在。')
            if changes.get('note') is not None:
                bookmark['note'] = changes['note'].strip() or bookmark['text']
            if changes.get('pinned') is not None:
                bookmark['pinned'] = changes['pinned']
            write_json(self.library.directory(paper_id) / 'bookmarks.json', bookmarks)
            return self._present(bookmark, self.library.read(paper_id))

    def delete(self, paper_id, bookmark_id):
        with self.library.file_locks.hold(paper_id), self.library.lock:
            bookmarks = self._read(paper_id)
            remaining = [item for item in bookmarks if item['id'] != bookmark_id]
            if len(remaining) == len(bookmarks):
                raise FileNotFoundError('书签不存在。')
            write_json(self.library.directory(paper_id) / 'bookmarks.json', remaining)
