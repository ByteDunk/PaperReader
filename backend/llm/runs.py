"""Keep an assistant generation alive briefly while its SSE subscriber reconnects."""
import asyncio
import hashlib
import json
import time

from .client import sse_event

DISCONNECT_GRACE_SECONDS = 60
FINISHED_TTL_SECONDS = 600
HEARTBEAT_SECONDS = 15
MAX_RUN_BYTES = 32 * 1024 * 1024
MAX_ACTIVE_RUNS = 8


class RunConflict(ValueError):
    pass


class Run:
    def __init__(self, fingerprint, generator):
        self.fingerprint = fingerprint
        self.generator = generator
        self.frames = []
        self.bytes = 0
        self.finished = False
        self.finished_at = 0
        self.subscribers = 0
        self.condition = asyncio.Condition()
        self.disconnect_task = None
        self.task = asyncio.create_task(self.produce())
        self.arm_disconnect()

    async def emit(self, event):
        sequence = len(self.frames) + 1
        frame = f'id: {sequence}\n' + sse_event({**event, 'sequence': sequence})
        async with self.condition:
            self.frames.append(frame)
            self.bytes += len(frame.encode('utf-8'))
            self.condition.notify_all()

    async def produce(self):
        try:
            async for frame in self.generator:
                event = json.loads(frame.split('\ndata: ', 1)[1])
                if self.bytes + len(frame.encode('utf-8')) > MAX_RUN_BYTES:
                    event = {'type': 'error', 'message': '本次生成的过程记录过大，已停止。请缩小问题范围后重试。'}
                await self.emit(event)
                if event['type'] in ('agent.done', 'error'):
                    break
            else:
                await self.emit({'type': 'error', 'message': '生成在完成前结束，请重新生成。'})
        except asyncio.CancelledError:
            await self.emit({'type': 'error', 'message': '已停止生成。'})
        except Exception:
            # Do not log or forward upstream content or credentials.
            await self.emit({'type': 'error', 'message': '生成任务中断，请重新生成。'})
        finally:
            try:
                await self.generator.aclose()
            finally:
                async with self.condition:
                    self.finished = True
                    self.finished_at = time.monotonic()
                    self.condition.notify_all()
                if self.disconnect_task and self.disconnect_task is not asyncio.current_task():
                    self.disconnect_task.cancel()

    def arm_disconnect(self):
        if self.finished or self.subscribers:
            return
        if self.disconnect_task:
            self.disconnect_task.cancel()

        async def expire():
            await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
            if not self.subscribers and not self.finished:
                await asyncio.shield(self.cancel())

        self.disconnect_task = asyncio.create_task(expire())

    async def cancel(self):
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        # Cancellation before the producer's first tick never enters its finally.
        if not self.finished:
            await self.generator.aclose()
            await self.emit({'type': 'error', 'message': '已停止生成。'})
            async with self.condition:
                self.finished = True
                self.finished_at = time.monotonic()
                self.condition.notify_all()

    async def events(self, after=0):
        self.subscribers += 1
        if self.disconnect_task:
            self.disconnect_task.cancel()
        try:
            while True:
                heartbeat = False
                async with self.condition:
                    pending = self.frames[after:]
                    if not pending:
                        if self.finished:
                            return
                        try:
                            await asyncio.wait_for(self.condition.wait(), HEARTBEAT_SECONDS)
                        except TimeoutError:
                            heartbeat = True
                if heartbeat:
                    yield ': keepalive\n\n'
                for frame in pending:
                    after += 1
                    yield frame
        finally:
            self.subscribers -= 1
            self.arm_disconnect()


class RunStore:
    def __init__(self):
        self.runs = {}

    def prune(self):
        cutoff = time.monotonic() - FINISHED_TTL_SECONDS
        self.runs = {key: run for key, run in self.runs.items()
                     if not run.finished or run.finished_at > cutoff}

    def get(self, run_id):
        self.prune()
        return self.runs.get(run_id)

    def start(self, body, create_generator):
        self.prune()
        run_id = body.request_id
        fingerprint = hashlib.sha256(body.model_dump_json(exclude={'request_id'}).encode()).hexdigest()
        if run_id in self.runs:
            run = self.runs[run_id]
            if run.fingerprint != fingerprint:
                raise RunConflict('相同请求标识不能用于不同的问题。')
            return run
        if sum(not run.finished for run in self.runs.values()) >= MAX_ACTIVE_RUNS:
            raise RunConflict('正在执行的助手任务过多，请先停止其他任务。')
        run = Run(fingerprint, create_generator())
        self.runs[run_id] = run
        return run

    async def shutdown(self):
        await asyncio.gather(*(run.cancel() for run in self.runs.values()), return_exceptions=True)
        timers = [run.disconnect_task for run in self.runs.values() if run.disconnect_task]
        for task in timers:
            task.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
        self.runs.clear()
