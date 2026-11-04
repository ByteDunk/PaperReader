"""Shared ownership, atomic file operations."""
import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def models_dir():
    return Path(os.environ.get('PAPERREADER_MODELS_DIR', PROJECT_ROOT / 'models')).resolve()


def mineru_home():
    runtime = os.environ.get('PAPERREADER_RUNTIME_DIR')
    return Path(runtime) / 'mineru' if runtime else models_dir() / '.mineru'


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_stamp(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_tree(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError('资源目录超出资料库范围。')
    if path.exists():
        shutil.rmtree(path)


class KeyedLocks:
    """Locks live only while acquired or waited on; release can cross threads."""
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}

    @contextmanager
    def hold(self, key):
        with self.lock:
            entry = self.entries.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self.lock:
                entry[1] -= 1
                if not entry[1]:
                    del self.entries[key]
