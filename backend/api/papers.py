import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import anyio
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..papers.library import MAX_UPLOAD


class PaperFileResponse(Response):
    def __init__(self, library, paper_id, resolve, **options):
        super().__init__()
        self.library, self.paper_id, self.resolve, self.options = library, paper_id, resolve, options

    async def __call__(self, scope, receive, send):
        lease = self.library.file_locks.hold(self.paper_id)
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(lease.__enter__)
        try:
            try:
                path = await run_in_threadpool(self.resolve)
                if not path.is_file():
                    raise FileNotFoundError()
                response = FileResponse(path, headers={'Cache-Control': 'no-store'}, **self.options)
            except FileNotFoundError:
                response = JSONResponse({'detail': '论文资源不存在。'}, status_code=404)
            await response(scope, receive, send)
        finally:
            lease.__exit__(None, None, None)


@contextmanager
def paper_errors(*, conflict=ValueError, unavailable=None):
    try:
        yield
    except FileNotFoundError as exc:
        raise HTTPException(404, '论文不存在。') from exc
    except conflict as exc:
        raise HTTPException(409, unavailable or str(exc)) from exc
    except OSError as exc:
        if unavailable is None:
            raise
        raise HTTPException(409, unavailable) from exc


router = APIRouter(prefix='/api/papers', tags=['papers'])


@router.post('/cache')
def clear_cache(request: Request, scope: Literal['partial', 'all'] = Query(default='partial')):
    try:
        return request.app.state.library.clear_cache(scope)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, '缓存暂时无法清理，请稍后重试。') from exc


class TranslationRetry(BaseModel):
    block_id: str | None = Field(default=None, max_length=100)
    failed_only: bool = False


@router.get('/{paper_id}/translation')
def get_translation(paper_id: str, request: Request, page: int | None = Query(default=None, ge=1)):
    with paper_errors(conflict=()):
        return request.app.state.library.translations.snapshot(paper_id, page)


@router.post('/{paper_id}/translation', status_code=202)
def retry_translation(paper_id: str, body: TranslationRetry, request: Request):
    with paper_errors():
        return request.app.state.library.translations.retry(paper_id, body.block_id, body.failed_only)


@router.get('')
def list_papers(request: Request):
    return request.app.state.library.list()


@router.post('', status_code=201)
async def import_paper(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, '请选择 PDF 文件。')
    library = request.app.state.library
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=library.root, suffix='.pdf', delete=False) as stream:
            path = Path(stream.name)
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, 'PDF 文件不能超过 50 MB。')
                stream.write(chunk)
        filename = file.filename.replace('\\', '/').rsplit('/', 1)[-1]
        return await run_in_threadpool(library.import_pdf, path, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()
        if path is not None:
            path.unlink(missing_ok=True)


@router.get('/{paper_id}')
def get_paper(paper_id: str, request: Request):
    with paper_errors(conflict=()):
        return request.app.state.library.read(paper_id)


@router.get('/{paper_id}/reflow')
def get_reflow(paper_id: str, request: Request):
    with paper_errors():
        return request.app.state.library.reflow(paper_id)


@router.post('/{paper_id}/reparse', status_code=202)
def reparse_paper(paper_id: str, request: Request):
    with paper_errors():
        return request.app.state.library.reparse(paper_id)


@router.delete('/{paper_id}', status_code=204)
def delete_paper(paper_id: str, request: Request):
    with paper_errors(unavailable='论文暂时无法删除，请稍后重试。'):
        request.app.state.library.delete(paper_id)
    return Response(status_code=204)


@router.get('/{paper_id}/pdf')
def get_pdf(paper_id: str, request: Request):
    paper = get_paper(paper_id, request)
    return PaperFileResponse(request.app.state.library, paper_id,
                             lambda: request.app.state.library.directory(paper_id) / 'original.pdf',
                        media_type='application/pdf', filename=paper['filename'], content_disposition_type='inline')


@router.get('/{paper_id}/pages/{number}.png')
def get_page(paper_id: str, number: int, request: Request, scale: int = Query(default=2, ge=1, le=8)):
    library = request.app.state.library
    return PaperFileResponse(library, paper_id, lambda: library.page_image(paper_id, number, scale), media_type='image/png')


@router.get('/{paper_id}/assets/{filename}')
def get_asset(paper_id: str, filename: str, request: Request, scale: int = Query(default=2, ge=1, le=8)):
    if not re.fullmatch(r'p\d+-b\d+\.png', filename):
        raise HTTPException(404, '图表不存在。')
    library = request.app.state.library
    return PaperFileResponse(library, paper_id, lambda: library.asset_image(paper_id, filename, scale), media_type='image/png')
