"""SQLite staging, atomic publication, substring, FTS5 and vec0 retrieval."""
import json
import re
import sqlite3
import threading
from contextlib import contextmanager

import sqlite_vec

from .embedding import DIMENSION


class IndexStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.needs_compaction = False
        self._initialize()

    def _initialize(self):
        with self.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(f'''
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id INTEGER PRIMARY KEY, paper_id TEXT UNIQUE NOT NULL,
                    revision TEXT NOT NULL, signature TEXT NOT NULL, ready INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                    block_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
                    section TEXT NOT NULL, sources TEXT NOT NULL, bbox TEXT NOT NULL,
                    char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, embedding BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS rag_chunks_document ON rag_chunks(document_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(text);
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors USING vec0(
                    embedding float[{DIMENSION}] distance_metric=cosine,
                    document_id integer
                );
            ''')

    def reset(self):
        with self.lock:
            if self.path.is_symlink() or self.path.resolve().parent != self.path.absolute().parent:
                raise ValueError('索引缓存超出资料库范围。')
            database = self.path.resolve()
            for path in (database, database.with_name(database.name + '-wal'), database.with_name(database.name + '-shm')):
                if path.is_symlink() or path.resolve().parent != database.parent:
                    raise ValueError('索引缓存超出资料库范围。')
                path.unlink(missing_ok=True)
            self.needs_compaction = False
            self._initialize()

    @contextmanager
    def connect(self):
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                connection.enable_load_extension(True)
                sqlite_vec.load(connection)
                connection.enable_load_extension(False)
                with connection:
                    yield connection
            finally:
                connection.close()

    def _clear(self, connection, document_id):
        rows = connection.execute('SELECT id FROM rag_chunks WHERE document_id=?', (document_id,)).fetchall()
        ids = [(row['id'],) for row in rows]
        connection.executemany('DELETE FROM rag_vectors WHERE rowid=?', ids)
        connection.executemany('DELETE FROM rag_fts WHERE rowid=?', ids)
        connection.execute('DELETE FROM rag_chunks WHERE document_id=?', (document_id,))

    def start(self, paper_id, revision, signature):
        with self.connect() as connection:
            row = connection.execute('SELECT id FROM rag_documents WHERE paper_id=?', (paper_id,)).fetchone()
            if row:
                self._clear(connection, row['id'])
                connection.execute('UPDATE rag_documents SET revision=?,signature=?,ready=0 WHERE id=?',
                                   (revision, signature, row['id']))
                return row['id']
            return connection.execute('INSERT INTO rag_documents(paper_id,revision,signature) VALUES(?,?,?)',
                                      (paper_id, revision, signature)).lastrowid

    def current(self, paper_id, signature):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM rag_documents WHERE paper_id=? AND signature=? AND ready=1',
                                     (paper_id, signature)).fetchone()
            return dict(row) if row else None

    def append(self, document_id, chunks, vectors):
        with self.connect() as connection:
            for chunk, vector in zip(chunks, vectors, strict=True):
                connection.execute('''INSERT INTO rag_chunks
                    (document_id,block_id,page,text,section,sources,bbox,char_start,char_end,embedding)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (document_id, chunk['block_id'], chunk['page'], chunk['text'], chunk['section'],
                     json.dumps(chunk['sources']), json.dumps(chunk['bbox']), chunk['char_start'],
                     chunk['char_end'], vector.astype('<f4').tobytes()))

    def publish(self, document_id):
        with self.connect() as connection:
            connection.execute('''INSERT INTO rag_vectors(rowid,embedding,document_id)
                SELECT id,embedding,document_id FROM rag_chunks WHERE document_id=?''', (document_id,))
            connection.execute('''INSERT INTO rag_fts(rowid,text)
                SELECT id,text FROM rag_chunks WHERE document_id=?''', (document_id,))
            connection.execute('UPDATE rag_documents SET ready=1 WHERE id=?', (document_id,))
            connection.execute("UPDATE rag_chunks SET embedding=x'' WHERE document_id=?", (document_id,))

    def remove(self, paper_id):
        with self.connect() as connection:
            row = connection.execute('SELECT id FROM rag_documents WHERE paper_id=?', (paper_id,)).fetchone()
            if row:
                self._clear(connection, row['id'])
                connection.execute('DELETE FROM rag_documents WHERE id=?', (row['id'],))
                self.needs_compaction = True

    def reconcile(self, paper_ids):
        with self.connect() as connection:
            stale = [row['paper_id'] for row in connection.execute('SELECT paper_id FROM rag_documents')
                     if row['paper_id'] not in paper_ids]
        for paper_id in stale:
            self.remove(paper_id)

    def compact(self, force=False):
        with self.lock:
            if not self.needs_compaction:
                return
            with self.connect() as connection:
                free = connection.execute('PRAGMA freelist_count').fetchone()[0]
                pages = connection.execute('PRAGMA page_count').fetchone()[0]
                if not force and free < max(256, pages // 4):
                    return
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                connection.execute('VACUUM')
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.needs_compaction = False

    def search(self, query, vector, document_id=None, limit=12):
        candidates = max(20, limit * 2)
        with self.connect() as connection:
            where = ' AND document_id=?' if document_id is not None else ''
            parameters = [vector.astype('<f4').tobytes(), candidates]
            if document_id is not None:
                parameters.append(document_id)
            dense = connection.execute(f'''SELECT rowid,distance FROM rag_vectors
                WHERE embedding MATCH ? AND k=?{where} ORDER BY distance''', parameters).fetchall()
            terms = re.findall(r'[A-Za-z][A-Za-z0-9_.-]*|[\u4e00-\u9fff]{2,}', query)[:24]
            lexical = []
            if terms:
                expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
                clause = ' AND c.document_id=?' if document_id is not None else ''
                parameters = [expression] + ([document_id] if document_id is not None else []) + [candidates]
                lexical = connection.execute(f'''SELECT rag_fts.rowid FROM rag_fts
                    JOIN rag_chunks c ON c.id=rag_fts.rowid JOIN rag_documents d ON d.id=c.document_id
                    WHERE rag_fts MATCH ? AND d.ready=1{clause} ORDER BY bm25(rag_fts) LIMIT ?''', parameters).fetchall()
            scores, distances = {}, {}
            for ranking in (dense, lexical):
                for rank, row in enumerate(ranking, 1):
                    scores[row['rowid']] = scores.get(row['rowid'], 0) + 1 / (60 + rank)
            for row in dense:
                distances[row['rowid']] = row['distance']
            # Search every ready chunk, independently of the semantic top-k.
            # Exclude the synthetic section prefix and treat SQL wildcards and
            # FTS syntax as literal text. casefold also handles non-ASCII case.
            folded_query = query.casefold()
            connection.create_function('contains_query', 2, lambda text, section: bool(folded_query)
                                       and folded_query in text.removeprefix(f'Section: {section}\n').casefold(),
                                       deterministic=True)
            clause = ' AND c.document_id=?' if document_id is not None else ''
            parameters = ([document_id] if document_id is not None else []) + [limit]
            exact = connection.execute(f'''SELECT MIN(c.id) AS rowid FROM rag_chunks c
                JOIN rag_documents d ON d.id=c.document_id
                WHERE d.ready=1{clause} AND contains_query(c.text,c.section)
                GROUP BY c.document_id,c.block_id ORDER BY rowid LIMIT ?''', parameters).fetchall()
            exact_ids = {row['rowid'] for row in exact}
            scores.update({chunk_id: 1.0 for chunk_id in exact_ids})
            if not scores:
                return []
            placeholders = ','.join('?' for _ in scores)
            rows = connection.execute(f'''SELECT c.id,c.block_id,c.page,c.text,c.section,
                c.sources,c.bbox,c.char_start,c.char_end,d.paper_id FROM rag_chunks c
                JOIN rag_documents d ON d.id=c.document_id
                WHERE c.id IN ({placeholders}) AND d.ready=1''', list(scores)).fetchall()
            chunks = {row['id']: row for row in rows}
            results, seen = [], set()
            for chunk_id in sorted(scores, key=lambda value: (value not in exact_ids, -scores[value], value)):
                row = chunks.get(chunk_id)
                if not row or (row['paper_id'], row['block_id']) in seen:
                    continue
                seen.add((row['paper_id'], row['block_id']))
                item = dict(row)
                item['text'] = item['text'].removeprefix(f'Section: {item["section"]}\n')
                item.update(sources=json.loads(item['sources']), bbox=json.loads(item['bbox']),
                            score=scores[chunk_id], similarity=1.0 if chunk_id in exact_ids else
                            1 - distances[chunk_id] if chunk_id in distances else None)
                results.append(item)
                if len(results) == limit:
                    break
            return results
