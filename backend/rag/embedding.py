"""One CPU model instance; runtime never downloads or substitutes weights."""
import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path

from ..resources import models_dir

MODEL_DIR = models_dir() / 'Qwen3-Embedding-0.6B-INT8'
MODEL_NAME = 'Qwen/Qwen3-Embedding-0.6B-Q'
DIMENSION = 1024
QUERY_PREFIX = 'Instruct: Given a question about academic papers, retrieve relevant passages that answer the question\nQuery:'
CHUNK_TOKENS = 480
OVERLAP_TOKENS = 48


class LocalEmbedding:
    def __init__(self, directory=MODEL_DIR):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.model = None
        self.tokenizer = None
        self.query_cache = OrderedDict()
        self.threads = 4
        self.batch_size = 4
        self.idle_seconds = 300
        self.model_threads = 4
        self.last_used = time.monotonic()
        self.validated = False
        self.manifest_stamp = None
        self.cached_signature = None

    @property
    def signature(self):
        manifest = self.directory / 'manifest.json'
        stat = manifest.stat() if manifest.exists() else None
        stamp = (stat.st_mtime_ns, stat.st_size) if stat else None
        if self.cached_signature is not None and stamp == self.manifest_stamp:
            return self.cached_signature
        source = manifest.read_text(encoding='utf-8') if stat else 'model-missing'
        config = {'model': MODEL_NAME, 'manifest': source, 'runtime': 'fastembed-0.9.0/onnxruntime-1.24.4',
                  'pooling': 'last-token', 'normalization': 'l2', 'dimension': DIMENSION,
                  'query_prefix': QUERY_PREFIX, 'chunk_tokens': CHUNK_TOKENS, 'overlap': OVERLAP_TOKENS,
                  'chunk_version': 1}
        self.manifest_stamp = stamp
        self.cached_signature = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        return self.cached_signature

    def _check_files(self):
        if self.validated:
            return
        names = ('onnx/model_quantized.onnx', 'tokenizer.json', 'config.json',
                 'tokenizer_config.json', 'special_tokens_map.json', 'manifest.json')
        if any(not (self.directory / name).is_file() for name in names):
            raise RuntimeError('本地 Qwen3 INT8 模型不完整，请重新启动桌面应用完成模型下载；开发环境请运行 python -m backend.model_download。')
        self.validated = True

    def split(self, text, prefix=''):
        with self.lock:
            self.last_used = time.monotonic()
            self._check_files()
            if self.tokenizer is None:
                from tokenizers import Tokenizer
                self.tokenizer = Tokenizer.from_file(str(self.directory / 'tokenizer.json'))
                self.tokenizer.no_truncation()
                self.tokenizer.no_padding()
            encoding = self.tokenizer.encode(text, add_special_tokens=False)
            prefix_size = len(self.tokenizer.encode(prefix, add_special_tokens=False).ids)
        budget = max(64, CHUNK_TOKENS - min(prefix_size, 128))
        offsets = encoding.offsets
        start = 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            left, right = offsets[start][0], offsets[end - 1][1]
            yield {'text': prefix + text[left:right], 'char_start': left, 'char_end': right}
            if end == len(offsets):
                break
            start = end - min(OVERLAP_TOKENS, budget // 4)

    def encode(self, texts, query=False):
        import numpy as np

        texts = list(texts)
        with self.lock:
            self.last_used = time.monotonic()
            self._check_files()
            values = [QUERY_PREFIX + text for text in texts] if query else texts
            cache_key = values[0] if query and len(values) == 1 else None
            if cache_key in self.query_cache:
                self.query_cache.move_to_end(cache_key)
                return self.query_cache[cache_key].copy()[None, :]
            if self.model is not None and self.model_threads != self.threads:
                self.model = None
            if self.model is None:
                from fastembed import TextEmbedding
                threads = self.threads
                self.model = TextEmbedding(model_name=MODEL_NAME, specific_model_path=str(self.directory),
                                           local_files_only=True, threads=threads,
                                           providers=['CPUExecutionProvider'])
                self.model_threads = threads
            vectors = list(self.model.embed(values, batch_size=self.batch_size, parallel=None))
            result = np.asarray(vectors, dtype=np.float32)
            if result.shape != (len(texts), DIMENSION) or not np.isfinite(result).all():
                raise RuntimeError('嵌入模型返回了无效向量。')
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            if (norms < 1e-8).any():
                raise RuntimeError('嵌入模型返回了空向量。')
            result = result / norms
            if cache_key is not None:
                self.query_cache[cache_key] = result[0].copy()
                if len(self.query_cache) > 64:
                    self.query_cache.popitem(last=False)
            self.last_used = time.monotonic()
            return result

    def configure(self, options):
        # An active inference completes before the next call reloads its session.
        self.threads = options['embedding_threads']
        self.batch_size = options['index_batch_size']
        self.idle_seconds = options['model_idle_minutes'] * 60

    def close(self):
        with self.lock:
            self.model = self.tokenizer = None
            self.query_cache.clear()
            self.validated = False

    def release_idle(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if time.monotonic() - self.last_used >= self.idle_seconds:
                self.close()
        finally:
            self.lock.release()
