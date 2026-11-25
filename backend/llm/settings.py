"""The project .env is the single source of truth for model configuration."""
import hashlib
import io
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from ..resources import file_stamp

ENV_PATH = Path(__file__).resolve().parents[2] / '.env'
FIELDS = {'base_url': 'LLM_BASE_URL', 'model': 'LLM_MODEL', 'api_key': 'LLM_API_KEY'}


class SettingsError(ValueError):
    pass


class SettingsConflict(SettingsError):
    pass


# field: (environment variable, default, minimum, maximum)
RESOURCE_SETTINGS = {
    'concurrency': ('LLM_TRANSLATION_CONCURRENCY', 5, 1, 30),
    'translation_batch_size': ('LLM_TRANSLATION_BATCH_SIZE', 10, 1, 20),
    'index_batch_size': ('RAG_BATCH_SIZE', 4, 1, 16),
    'embedding_threads': ('RAG_CPU_THREADS', 6, 1, 16),
    'model_idle_minutes': ('RAG_IDLE_MINUTES', 5, 1, 60),
}


def resource_settings(source):
    return _resource_values(dotenv_values(stream=io.StringIO(source), interpolate=False))


def _resource_values(parsed):
    result = {}
    for field, (name, default, minimum, maximum) in RESOURCE_SETTINGS.items():
        try:
            value = int(parsed.get(name, default))
            result[field] = value if minimum <= value <= maximum else default
        except (ValueError, TypeError):
            result[field] = default
    return result


def validate_settings(values, *, require_complete=True):
    url = values['base_url'].strip().rstrip('/')
    try:
        parts = urlsplit(url)
        valid = (parts.scheme in ('https', 'http') and parts.hostname and parts.port != 0
                 and not parts.username and not parts.password and not parts.query and not parts.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in url))
    except ValueError:
        valid = False
    if (url or require_complete) and not valid:
        raise SettingsError('API 地址必须是有效的 HTTP(S) 地址，不含认证信息、查询参数或片段。')
    model = values['model'].strip()
    if (require_complete and not model) or any(ord(c) < 32 for c in model):
        raise SettingsError('模型名称不能为空或包含控制字符。')
    key = values['api_key'].strip()
    if any(ord(c) < 32 or ord(c) > 126 for c in key):
        raise SettingsError('API Key 只能包含可打印的 ASCII 字符。')
    return {'base_url': url, 'model': model, 'api_key': key}


class SettingsStore:
    def __init__(self, path=ENV_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.cached = None
        self.stamp = None

    def _read(self):
        try:
            try:
                stamp = file_stamp(self.path)
            except FileNotFoundError:
                stamp = None
            if self.cached is not None and stamp == self.stamp:
                return self.cached
            raw = self.path.read_bytes() if stamp is not None else b''
            source = raw.decode('utf-8-sig')
        except (OSError, UnicodeError) as exc:
            raise SettingsError('无法读取项目根目录 .env，请检查文件权限和 UTF-8 编码。') from exc
        parsed = dotenv_values(stream=io.StringIO(source), interpolate=False)
        # Expose editable fields even when a hand-edited file has invalid values;
        # validation occurs on save and immediately before an upstream request.
        values = {
            'base_url': (parsed.get('LLM_BASE_URL') or '').strip().rstrip('/'),
            'model': (parsed.get('LLM_MODEL') or '').strip(),
            'api_key': (parsed.get('LLM_API_KEY', '') or '').strip(),
            'translate_references': str(parsed.get('LLM_TRANSLATE_REFERENCES', 'false')).strip().lower() in ('true', '1', 'yes', 'on'),
            'auto_translate': str(parsed.get('LLM_AUTO_TRANSLATE', 'true')).strip().lower() in ('true', '1', 'yes', 'on'),
            **_resource_values(parsed),
        }
        self.stamp = stamp
        self.cached = (source, values, hashlib.sha256(raw).hexdigest())
        return self.cached

    def read(self):
        with self.lock:
            _, values, revision = self._read()
            return dict(values), revision

    def public(self):
        with self.lock:
            _, values, revision = self._read()
            return {k: v for k, v in values.items() if k != 'api_key'} | {
                'api_key_configured': bool(values['api_key']), 'revision': revision,
            }

    def resources(self):
        values, _ = self.read()
        return {key: values[key] for key in RESOURCE_SETTINGS}

    def update(self, base_url, model, api_key, revision, translate_references=None, auto_translate=None, **resources):
        with self.lock:
            source, current, current_revision = self._read()
            if revision != current_revision:
                raise SettingsConflict('.env 已被修改，请重新载入设置后再保存。')
            values = validate_settings({'base_url': current['base_url'] if base_url is None else base_url,
                                        'model': current['model'] if model is None else model,
                                        'api_key': api_key if api_key is not None and api_key.strip() else current['api_key']},
                                       require_complete=False)
            fields = dict(FIELDS)
            for field, value, name, label in (
                ('translate_references', translate_references, 'LLM_TRANSLATE_REFERENCES', '翻译参考文献'),
                ('auto_translate', auto_translate, 'LLM_AUTO_TRANSLATE', '导入后自动翻译'),
            ):
                if value is not None:
                    if type(value) is not bool:
                        raise SettingsError(f'{label}必须为布尔值。')
                    fields[field] = name
                    values[field] = value
            for field, value in resources.items():
                if field not in RESOURCE_SETTINGS:
                    raise SettingsError('未知资源设置。')
                if value is None:
                    continue
                name, _, minimum, maximum = RESOURCE_SETTINGS[field]
                if type(value) is not int or not minimum <= value <= maximum:
                    raise SettingsError(f'{field} 必须为 {minimum} 到 {maximum} 的整数。')
                fields[field] = name
                values[field] = value
            # Remove managed assignments, including quoted multiline values. Keep
            # unrelated variables and comments exactly as they were.
            assignments = re.compile(
                r'^(?:[ \t]*export[ \t]+)?[ \t]*(' + '|'.join(fields.values()) + r')[ \t]*=[ \t]*'
                r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^\r\n]*)[^\r\n]*(?:\r?\n|$)',
                re.MULTILINE,
            )
            source = assignments.sub('', source)
            if source and not source.endswith('\n'):
                source += '\n'
            for field, name in fields.items():
                # dotenv understands quoted backslash and quote escapes.
                source += f'{name}={json.dumps(values[field], ensure_ascii=False)}\n'
            self._write(source, current_revision)
            return self.public()

    def _write(self, source, revision):
        # Called with the shared lock: API and translation settings cannot
        # overwrite each other's assignments.
        temp_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                             dir=self.path.parent, prefix='.env-', delete=False) as file:
                temp_path = Path(file.name)
                file.write(source)
                file.flush()
                os.fsync(file.fileno())
            if self._read()[2] != revision:
                raise SettingsConflict('.env 已被修改，请重新载入设置后再保存。')
            os.replace(temp_path, self.path)
            self.cached = None
        except OSError as exc:
            raise SettingsError('无法保存项目根目录 .env，请检查文件权限。') from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
