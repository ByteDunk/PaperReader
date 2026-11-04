import asyncio
import hashlib
import logging
import re
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ..parse.pdf import PARSER_VERSION, extract_pdf, pdf_info, render_region
from ..resources import KeyedLocks, file_stamp, read_json, remove_tree, write_json
from ..llm.settings import resource_settings
from .bookmarks import Bookmarks

logger = logging.getLogger(__name__)
MAX_UPLOAD = 50 * 1024 * 1024


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.cache_cleanup_lock = threading.Lock()
        self.clearing_cache = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pdf-parser')
        self.options = resource_settings('')
        self.closing = False
        self.deleting = set()
        self.cancel_events = {}
        self.metadata = {}
        self.file_locks = KeyedLocks()
        self.jobs = {}
        self.paper_locks = KeyedLocks()
        self.translations = None
        self.rag = None
        self.bookmarks = Bookmarks(self)

    def paper_lock(self, paper_id):
        return self.paper_locks.hold(paper_id)

    def _services(self):
        return filter(None, (self.translations, self.rag))

    def configure(self, options):
        with self.lock:
            self.options.update({key: options[key] for key in self.options if key in options})
            if self.rag:
                self.rag.configure(self.options)
        if self.translations and 'translate_references' in options:
            self.translations.configure(options['translate_references'])

    def schedule_parse(self, paper_id):
        with self.lock:
            previous = self.jobs.get(paper_id)
            if (self.closing or self.clearing_cache or paper_id in self.deleting
                    or previous is not None and not previous.done()):
                return
            cancel = threading.Event()
            self.cancel_events[paper_id] = cancel
            job = self.executor.submit(self.parse, paper_id, cancel)
            self.jobs[paper_id] = job
            def completed(future):
                with self.lock:
                    if self.jobs.get(paper_id) is future:
                        self.jobs.pop(paper_id, None)
                        self.cancel_events.pop(paper_id, None)
            job.add_done_callback(completed)

    def _cancel_parse(self, paper_id):
        # The caller holds the library lock; waiting always happens outside it.
        cancel = self.cancel_events.get(paper_id)
        if cancel:
            cancel.set()
        job = self.jobs.get(paper_id)
        if job:
            job.cancel()

    def directory(self, paper_id):
        if not re.fullmatch(r'[0-9a-f]{64}', paper_id):
            raise FileNotFoundError('论文不存在')
        return self.root / paper_id

    def read(self, paper_id):
        with self.lock:
            path = self.directory(paper_id) / 'paper.json'
            stamp = file_stamp(path)
            cached = self.metadata.get(paper_id)
            if cached is None or cached[0] != stamp:
                cached = (stamp, read_json(path))
                self.metadata[paper_id] = cached
            return deepcopy(cached[1])

    def save(self, paper):
        with self.lock:
            path = self.directory(paper['id']) / 'paper.json'
            write_json(path, paper)
            self.metadata[paper['id']] = (file_stamp(path), deepcopy(paper))

    def list(self):
        with self.lock:
            return sorted([self.read(p.parent.name) for p in self.root.glob('*/paper.json')],
                          key=lambda p: p['added_at'], reverse=True)

    def reflow(self, paper_id):
        with self.lock:
            paper = self.read(paper_id)
            if paper['state'] != 'ready':
                raise ValueError(paper['error'] or '论文正在重排，请稍候。')
            return read_json(self.directory(paper_id) / 'reflow.json')

    def resume(self):
        # Only app-owned transient files are removed. Published paper data stays.
        for pattern in ('tmp*.pdf', '*/*.tmp', '*/pages/*.tmp.png', '*/assets/hd/*.tmp.png'):
            for path in self.root.glob(pattern):
                path.unlink(missing_ok=True)
        papers = self.list()
        if self.rag:
            self.rag.reconcile({paper['id'] for paper in papers})
        for paper in papers:
            if paper['state'] == 'parsing' or (paper['state'] == 'ready' and paper.get('parser_version') != PARSER_VERSION):
                paper.update(state='parsing', parse_progress=0)
                self.save(paper)
                self.schedule_parse(paper['id'])
            elif paper['state'] == 'ready':
                for service in self._services():
                    service.restore_ready(paper['id'])

    def import_pdf(self, path, filename):
        with path.open('rb') as stream:
            if stream.read(1024).find(b'%PDF-') < 0:
                raise ValueError('文件不是有效的 PDF。')
            stream.seek(0)
            paper_id = hashlib.file_digest(stream, 'sha256').hexdigest()
        with self.paper_lock(paper_id):
            with self.lock:
                if self.clearing_cache:
                    raise ValueError('缓存正在清理，请稍后重新导入。')
                if paper_id in self.deleting:
                    raise ValueError('论文正在删除，请稍后重新导入。')
            if (self.directory(paper_id) / 'paper.json').exists():
                paper = self.read(paper_id)
                if paper['state'] in ('failed', 'unparsed') or (paper['state'] == 'ready' and paper.get('parser_version') != PARSER_VERSION):
                    paper.update(state='parsing', error='', parse_progress=0)
                    self.save(paper)
                    self.schedule_parse(paper_id)
                return paper
            try:
                info = pdf_info(path)
                if not info['pages']:
                    raise ValueError('PDF 没有页面。')
                paper = {'id': paper_id, 'filename': filename,
                         'title': info.get('Title') or Path(filename).stem,
                         'authors': info.get('Author', ''), 'pages': info['pages'],
                         'state': 'parsing', 'parse_progress': 0, 'error': '', 'warnings': [],
                         'added_at': datetime.now(timezone.utc).isoformat()}
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError('PDF 无法读取，可能已损坏或需要密码。') from exc
            directory = self.directory(paper_id)
            directory.mkdir(parents=True, exist_ok=True)
            path.replace(directory / 'original.pdf')
            self.save(paper)
            self.schedule_parse(paper_id)
            return paper

    def parse(self, paper_id, cancel):
        with self.paper_lock(paper_id):
            if not cancel.is_set() and not self.closing and (self.directory(paper_id) / 'paper.json').exists():
                self._parse(paper_id, cancel)

    def _parse(self, paper_id, cancel):
        paper = self.read(paper_id)
        directory = self.directory(paper_id)
        def check_cancel():
            if cancel.is_set():
                raise CancelledError()

        def update_progress(value):
            check_cancel()
            with self.lock:
                current = self.read(paper_id)
                if current.get('parse_progress') != value:
                    current['parse_progress'] = value
                    self.save(current)

        revisions = []
        try:
            check_cancel()
            with self.file_locks.hold(paper_id):
                remove_tree(directory, directory / 'assets')
            with self.lock:
                check_cancel()
                for service in self._services():
                    revisions.append((service, service.start_source(paper_id)))
            def publish_blocks(blocks):
                check_cancel()
                for service, revision in revisions:
                    service.add_blocks(paper_id, revision, blocks)
            result = extract_pdf(directory / 'original.pdf', directory / 'assets', on_progress=update_progress,
                                 on_blocks=publish_blocks if revisions else None,
                                 is_cancelled=cancel.is_set)
            result['title'] = result['title'] or paper['title']
            check_cancel()
            write_json(directory / 'reflow.json', result)
            with self.lock:
                paper = self.read(paper_id)
                paper.update(state='ready', parse_progress=100, parser_version=PARSER_VERSION, title=result['title'],
                             authors=result['authors'], warnings=result['warnings'])
                self.save(paper)
            for service, revision in revisions:
                if revision:
                    service.finish_source(paper_id, revision)
        except CancelledError:
            return
        except Exception:
            if cancel.is_set():
                return
            logger.exception('PDF reflow failed: %s', paper_id)
            with self.lock:
                paper = self.read(paper_id)
                paper.update(state='failed', error='PDF 重排失败，原文仍可阅读。请重新导入以重试。')
                self.save(paper)
            for service, revision in revisions:
                if revision:
                    service.fail_source(paper_id, revision)

    def reparse(self, paper_id):
        with self.lock:
            if self.clearing_cache:
                raise ValueError('缓存正在清理，请稍后重新重排。')
            paper = self.read(paper_id)
            job = self.jobs.get(paper_id)
            if job is not None and not job.done():
                return paper
            paper.update(state='parsing', parse_progress=0, error='', warnings=[])
            self.save(paper)
            self.schedule_parse(paper_id)
            return paper

    def delete(self, paper_id):
        # Signal cancellation before waiting for parser/file owners. No late
        # translation or embedding result can recreate a deleted generation.
        with self.lock:
            if self.clearing_cache:
                raise ValueError('缓存正在清理，请稍后删除论文。')
            self.read(paper_id)
            self.deleting.add(paper_id)
            self._cancel_parse(paper_id)
            for service in self._services():
                service.remove(paper_id)
        try:
            with self.paper_lock(paper_id), self.file_locks.hold(paper_id), self.lock:
                remove_tree(self.root, self.directory(paper_id))
                self.metadata.pop(paper_id, None)
                self.jobs.pop(paper_id, None)
                self.cancel_events.pop(paper_id, None)
        finally:
            with self.lock:
                self.deleting.discard(paper_id)

    def page_image(self, paper_id, number, scale=2):
        paper = self.read(paper_id)
        if number < 1 or number > paper['pages']:
            raise FileNotFoundError('页码不存在')
        directory = self.directory(paper_id)
        cache = directory / 'pages'
        cache.mkdir(exist_ok=True)
        target = cache / (f'{number}.png' if scale == 2 else f'{number}@{scale}x.png')
        return self._render_image(directory, target, number, None, scale)

    def _render_image(self, directory, target, number, bbox, scale):
        if not target.exists():
            temporary = target.with_suffix('.tmp.png')
            try:
                render_region(directory / 'original.pdf', number - 1, bbox, temporary, scale=scale)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def asset_image(self, paper_id, filename, scale=2):
        if not re.fullmatch(r'p\d+-b\d+\.png', filename):
            raise FileNotFoundError('图表不存在')
        directory = self.directory(paper_id)
        original = directory / 'assets' / filename
        if scale == 2 or not original.is_file():
            return original
        cache = directory / 'assets' / 'hd'
        target = cache / f'{Path(filename).stem}@{scale}x.png'
        if target.exists():
            return target
        try:
            document = self.reflow(paper_id)
        except ValueError:
            return original
        region = document.get('assets', {}).get(filename)
        if not region:
            # Upgrade existing figure/table/equation assets without reparsing.
            region = next((block for block in document['blocks'] if block.get('asset') == filename), None)
        if not region or not region.get('bbox'):
            # Older inline formulas lack their precise crop; retain the image.
            return original
        cache.mkdir(exist_ok=True)
        return self._render_image(directory, target, region['page'], region['bbox'], scale)

    def clear_cache(self, scope='partial'):
        if scope not in ('partial', 'all'):
            raise ValueError('未知缓存清理范围。')
        with self.cache_cleanup_lock:
            if scope == 'all':
                return self._clear_all_cache()
            return self._clear_partial_cache()

    def _clear_partial_cache(self):
        removed = 0
        for path in self.root.glob('*/paper.json'):
            paper_id = path.parent.name
            with self.file_locks.hold(paper_id):
                pages = self.directory(paper_id) / 'pages'
                removed += sum(1 for image in pages.glob('*.png') if image.is_file())
                remove_tree(self.directory(paper_id), pages)
                assets = self.directory(paper_id) / 'assets'
                remove_tree(assets, assets / 'hd')
        with self.lock:
            self.metadata.clear()
        # Wait for active inference outside the library lock. The next search
        # or indexing batch will load the retrieval model again when needed.
        for service in self._services():
            service.clear_cache()
        return {'pages_removed': removed, 'scope': 'partial'}

    def _clear_all_cache(self):
        removed = 0
        with self.lock:
            self.clearing_cache = True
        try:
            with self.lock:
                papers = self.list()
                jobs = list(self.jobs.values())
                for paper_id in list(self.jobs):
                    self._cancel_parse(paper_id)
                # Invalidate generations before waiting, so late translation
                # and embedding responses cannot publish files or indexes.
                for paper in papers:
                    paper_id = paper['id']
                    for service in self._services():
                        service.remove(paper_id)
                    paper.update(state='unparsed', parse_progress=0, error='', warnings=[])
                    for key in ('parser_version', 'translation', 'index'):
                        paper.pop(key, None)
                    self.save(paper)
            # Parsers own paper locks and may need the library lock to exit.
            wait(jobs)
            for paper in papers:
                paper_id = paper['id']
                with self.paper_lock(paper_id), self.file_locks.hold(paper_id):
                    directory = self.directory(paper_id)
                    # A parser may have passed its final cancellation check
                    # before cleanup began. Replace any late ready metadata.
                    self.save(paper)
                    removed += sum(1 for image in (directory / 'pages').glob('*.png') if image.is_file())
                    for path in directory.iterdir():
                        if path.name in ('original.pdf', 'paper.json', 'bookmarks.json'):
                            continue
                        # Every target is a direct child of the validated paper
                        # directory; never follow links outside the library.
                        if path.is_symlink() or path.resolve().parent != directory:
                            raise ValueError('缓存目录超出资料库范围。')
                        if path.is_dir():
                            remove_tree(directory, path)
                        else:
                            path.unlink(missing_ok=True)
            # Drain index workers and release inference outside the library
            # lock, then remove the on-disk index and create an empty database.
            for service in self._services():
                service.clear_cache(full=True)
            with self.lock:
                self.metadata.clear()
            return {'pages_removed': removed, 'scope': 'all'}
        finally:
            with self.lock:
                self.clearing_cache = False

    def stop(self):
        with self.lock:
            self.closing = True
            for paper_id in list(self.jobs):
                self._cancel_parse(paper_id)

    def maintain(self, options):
        self.configure(options)
        if self.rag:
            self.rag.maintain()

    async def aclose(self):
        # Drain producers before closing their consumers and persistence writer.
        self.stop()
        try:
            await asyncio.to_thread(self.shutdown)
        finally:
            try:
                if self.translations:
                    await self.translations.shutdown()
            finally:
                if self.rag:
                    await asyncio.to_thread(self.rag.shutdown)

    def shutdown(self):
        self.stop()
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            self.jobs.clear()
            self.cancel_events.clear()
            self.metadata.clear()
