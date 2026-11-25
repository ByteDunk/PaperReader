"""Explicit ModelScope setup before importing or resuming the application."""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue

import httpx

from .model_catalog import MODEL_GROUPS, missing_model_files, validate_models
from .resources import checksum


class DownloadPaused(Exception):
    """All download workers have stopped and their partial files are closed."""


def setup_summary(directory, groups=MODEL_GROUPS):
    missing = {(group['id'], name) for group, name in missing_model_files(directory, groups)}
    return {'groups': [dict(id=group['id'], title=group['title'],
                           total_bytes=sum(size for name, (size, _) in group['files'].items()
                                           if (group['id'], name) in missing))
                       for group in groups]}


def download_models(directory, report, groups=MODEL_GROUPS, client=None, pause=None, pending=None):
    """Download up to three assets concurrently, resuming and verifying each one."""
    directory = Path(directory)
    pause = pause if pause is not None else threading.Event()
    if client is None:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20), trust_env=False) as client:
            return download_models(directory, report, groups, client, pause, pending)
    pending = sorted(pending if pending is not None else missing_model_files(directory, groups),
                     key=lambda item: item[0]['files'][item[1]][0], reverse=True)
    progress = [0] * len(pending)
    stages = ['preparing'] * len(pending)
    for index, (group, name) in enumerate(pending):
        size = group['files'][name][0]
        target = directory / group['folder'] / name
        partial = target.with_name(target.name + '.part')
        if target.is_file() and target.stat().st_size == size:
            progress[index], stages[index] = size, 'verified'
        elif partial.is_file() and partial.stat().st_size <= size:
            progress[index] = partial.stat().st_size
    group_files = {group['id']: [i for i, (item, _) in enumerate(pending) if item['id'] == group['id']]
                   for group in groups}
    summary = [dict(id=group['id'], title=group['title'],
                    total_bytes=sum(pending[i][0]['files'][pending[i][1]][0] for i in group_files[group['id']]))
               for group in groups]
    group_transferred = {group['id']: 0 for group in groups}
    group_started = {}
    last_report = 0
    progress_lock = threading.Lock()
    stopped = threading.Event()

    def interrupted():
        return stopped.is_set() or pause.is_set()

    def publish(force=False):
        nonlocal last_report
        now = time.monotonic()
        if not force and now - last_report < .2:
            return
        last_report = now
        group_progress = []
        for model in summary:
            indices = group_files[model['id']]
            active = {stages[i] for i in indices}
            model_stage = next((value for value in ('failed', 'transferring', 'retrying', 'verifying', 'preparing')
                                if value in active), 'verified')
            model_downloaded = sum(progress[i] for i in indices)
            model_remaining = model['total_bytes'] - model_downloaded
            model_started = group_started.get(model['id'])
            model_speed = (group_transferred[model['id']] / max(now - model_started, .001)
                           if model_started is not None and model_stage not in ('verified', 'failed') else 0)
            group_progress.append(dict(model, stage=model_stage,
                                       downloaded_bytes=model_downloaded, bytes_per_second=model_speed,
                                       remaining_seconds=(0 if not model_remaining else
                                                          model_remaining / model_speed if model_speed > 0 else None)))
        report(dict(phase='downloading', groups=group_progress))

    def download(index, group, name):
        if interrupted() or stages[index] == 'verified':
            return
        size, expected_hash = group['files'][name]
        target = directory / group['folder'] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.part')
        received = 0

        def update(stage, force=False, delta=0):
            with progress_lock:
                progress[index] = received
                stages[index] = stage
                group_transferred[group['id']] += delta
                group_started.setdefault(group['id'], time.monotonic())
                publish(force)

        for attempt in range(3):
            if interrupted():
                return
            received = 0
            try:
                offset = partial.stat().st_size if partial.is_file() else 0
                if offset > size:
                    partial.unlink()
                    offset = 0
                received = offset
                update('preparing')
                if offset < size:
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    url = f"https://modelscope.cn/api/v1/models/{group['repository']}/repo"
                    with client.stream('GET', url, params={'Revision': group['revision'], 'FilePath': name},
                                       headers=headers) as response:
                        response.raise_for_status()
                        append = bool(offset and response.status_code == 206)
                        if response.status_code == 206:
                            expected_range = f'bytes {offset if append else 0}-'
                            if not response.headers.get('Content-Range', '').startswith(expected_range):
                                partial.unlink(missing_ok=True)
                                raise RuntimeError('下载服务器返回了错误的续传范围。')
                        received = offset if append else 0
                        update('transferring', True)
                        with partial.open('ab' if append else 'wb') as stream:
                            for chunk in response.iter_bytes(256 * 1024):
                                if interrupted():
                                    return
                                if received + len(chunk) > size:
                                    raise RuntimeError(f'下载文件大小异常：{name}')
                                stream.write(chunk)
                                received += len(chunk)
                                update('transferring', delta=len(chunk))
                if interrupted():
                    return
                update('verifying', True)
                if partial.stat().st_size != size or checksum(partial) != expected_hash:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError(f'文件校验失败：{name}')
                partial.replace(target)
                update('verified', True)
                break
            except (httpx.HTTPError, RuntimeError):
                if interrupted():
                    return
                if attempt == 2:
                    stopped.set()
                    update('failed', True)
                    raise
                update('retrying', True)
                time.sleep(1 + attempt)

    publish(force=True)
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='model-download') as executor:
        futures = [executor.submit(download, index, group, name) for index, (group, name) in enumerate(pending)]
        try:
            for future in as_completed(futures):
                future.result()
        except Exception:
            stopped.set()
            for future in futures:
                future.cancel()
            raise
    if pause.is_set() and any(stage != 'verified' for stage in stages):
        with progress_lock:
            publish(force=True)
        raise DownloadPaused()


def prepare_models(directory, report=None, commands=None):
    """Wait for affirmative native-window consent; no network is used before it."""
    if report is None:
        def report(value):
            # Frozen Python can use the Windows code page despite PYTHONIOENCODING.
            # ASCII JSON keeps the native UTF-8 pipe lossless for every locale.
            print(json.dumps({'event': 'paperreader_models', **value}, ensure_ascii=True), flush=True)
    commands = commands if commands is not None else sys.stdin
    pending = missing_model_files(directory)
    if not pending:
        validate_models(directory)
        return True
    report(dict(phase='confirm', **setup_summary(directory)))
    incoming = Queue()
    accepted, pause = threading.Event(), threading.Event()

    def read_commands():
        try:
            # Read the native pipe without holding stdin's buffered-reader lock
            # while the daemon waits, so normal application shutdown stays clean.
            source = getattr(getattr(commands, 'buffer', None), 'raw', commands) if commands is sys.stdin else commands
            for line in source:
                if isinstance(line, bytes):
                    line = line.decode('ascii', errors='replace')
                command = line.strip()
                if command == 'pause':
                    pause.set()
                else:
                    accepted.clear()
                    incoming.put(command)
                    accepted.wait()  # Start this attempt before reading its pause command.
        finally:
            incoming.put(None)

    threading.Thread(target=read_commands, name='model-commands', daemon=True).start()
    while incoming.get() == 'download':
        pause.clear()
        accepted.set()
        latest_progress = {}

        def report_progress(value):
            latest_progress.update(value)
            report(value)

        try:
            download_models(directory, report_progress, pause=pause, pending=pending)
            validate_models(directory)
        except DownloadPaused:
            progress = dict(latest_progress or setup_summary(directory), phase='paused', error=None)
            progress['groups'] = [dict(group, bytes_per_second=0, remaining_seconds=None)
                                  for group in progress['groups']]
            report(progress)
        except Exception as error:
            report(dict(latest_progress or setup_summary(directory), phase='download_error',
                        error=f'模型下载失败：{error}'))
        else:
            report(dict(phase='starting'))
            return True
    return False


def _run_cli(directory):
    pending = missing_model_files(directory)
    if not pending:
        validate_models(directory)
        print('本地模型已就绪。')
        return 0

    mib = 1024 ** 2
    total = sum(group['files'][name][0] for group, name in pending)
    prompt = f'需要从 ModelScope 下载约 {total / mib:.1f} MiB 的模型文件，是否继续？[yes/no，默认 no] '
    while True:
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            answer = ''
        if answer in ('yes', 'y'):
            break
        if answer in ('no', 'n', ''):
            print('已取消下载。')
            return 1
        print('请输入 yes 或 no。')

    interactive = sys.stderr.isatty()
    last_milestone = None
    stage_labels = {'failed': '已失败', 'retrying': '重试中', 'transferring': '下载中',
                    'verifying': '校验中', 'preparing': '准备中', 'verified': '已校验'}

    def report_progress(value):
        nonlocal last_milestone
        groups = value['groups']
        downloaded = sum(group['downloaded_bytes'] for group in groups)
        percent = 100 * downloaded // total
        active = {group['stage'] for group in groups}
        stage = next(label for state, label in stage_labels.items() if state in active)
        milestone = (percent // 5, stage)
        if not interactive and milestone == last_milestone:
            return
        last_milestone = milestone
        filled = 24 * downloaded // total
        bar = '#' * filled + '-' * (24 - filled)
        print(f'[{bar}] {percent:3d}% {downloaded / mib:8.1f}/{total / mib:.1f} MiB {stage}',
              file=sys.stderr, end='\r' if interactive else '\n', flush=True)

    try:
        try:
            download_models(directory, report_progress, pending=pending)
        finally:
            if interactive:
                print(file=sys.stderr)
        validate_models(directory)
    except (OSError, RuntimeError, httpx.HTTPError) as error:
        print(f'模型下载失败：{error}', file=sys.stderr)
        return 1

    print('模型下载并校验完成。')
    return 0


if __name__ == '__main__':
    from .resources import models_dir

    raise SystemExit(_run_cli(models_dir()))
