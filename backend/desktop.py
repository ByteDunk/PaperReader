"""Private loopback transport for the Tauri-owned backend process."""
import hmac
import json
import os
import re
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse


RESOURCE = re.compile(r'^/api/papers/[0-9a-f]{64}/(?:pages/[1-9][0-9]*\.png|assets/(?:[0-9a-f]{32}-)?p[0-9]+-b[0-9]+\.png|pdf)$')
ORIGIN = 'http://tauri.localhost'


class DesktopAccess:
    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = dict(scope['headers'])
            credential = headers.get(b'x-paperreader-token', b'').decode('ascii', errors='replace')
            if scope['method'] in ('GET', 'HEAD') and RESOURCE.fullmatch(scope['path']):
                query = parse_qs(scope['query_string'].decode('ascii', errors='replace'))
                credential = credential or query.get('desktop_token', [''])[0]
            if not hmac.compare_digest(credential.encode(), self.token.encode()):
                await JSONResponse({'detail': '桌面会话已失效，请重新打开应用。'}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_desktop_app(data_dir, token, stop, ready=None):
    from .main import create_app

    root = Path(data_dir).resolve()
    app = create_app(data_dir=root / 'library', env_path=root / 'config' / '.env')
    app.add_middleware(DesktopAccess, token=token)
    origins = [ORIGIN]
    if not getattr(sys, 'frozen', False):
        origins.extend(['http://localhost:5173', 'http://127.0.0.1:5173'])
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'],
                       allow_headers=['Content-Type', 'X-PaperReader-Token'])

    @app.get('/api/desktop/health')
    def health():
        return {'status': 'ready', 'pid': os.getpid()}

    @app.post('/api/desktop/shutdown', status_code=202)
    def shutdown():
        stop()
        return {'status': 'stopping'}

    if ready:
        lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def announce(application):
            async with lifespan(application):
                ready()
                yield

        app.router.lifespan_context = announce
    return app


def serve(data_dir, model_dir):
    import uvicorn

    root = Path(data_dir).resolve()
    for name in ('config', 'library', 'runtime', 'logs'):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ.update(PAPERREADER_DESKTOP='1', PAPERREADER_MODELS_DIR=str(Path(model_dir).resolve()),
                      PAPERREADER_RUNTIME_DIR=str(root / 'runtime'), HF_HUB_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
    token = os.environ.pop('PAPERREADER_SESSION_TOKEN', '')
    if len(token) < 32:
        raise RuntimeError('A desktop session token is required.')
    # Bind once to port zero; pass the same socket to Uvicorn to avoid a port race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]

        def ready():
            print(json.dumps({'event': 'paperreader_ready', 'url': f'http://127.0.0.1:{port}'}), flush=True)

        app = create_desktop_app(root, token, lambda: setattr(server, 'should_exit', True), ready)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, workers=1,
                                loop='asyncio', http='h11', ws='none', access_log=False,
                                log_level='info', timeout_graceful_shutdown=1))
        server.run(sockets=[listener])
