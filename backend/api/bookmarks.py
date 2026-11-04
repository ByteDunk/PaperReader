from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/bookmarks', tags=['bookmarks'])


class BookmarkCreate(BaseModel):
    paper_id: str = Field(min_length=64, max_length=64)
    block_id: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=2000)


class BookmarkUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    pinned: bool | None = None


def operate(operation):
    try:
        return operation()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc) or '论文或书签不存在。') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(409, '书签暂时无法保存，请稍后重试。') from exc


@router.get('')
def list_bookmarks(request: Request, scope: Literal['paper', 'all'] = Query(default='all'), paper_id: str | None = None):
    if scope == 'paper' and not paper_id:
        raise HTTPException(422, '请选择当前论文。')
    return operate(lambda: request.app.state.library.bookmarks.list(paper_id if scope == 'paper' else None))


@router.post('', status_code=201)
def create_bookmark(body: BookmarkCreate, request: Request):
    return operate(lambda: request.app.state.library.bookmarks.add(body.paper_id, body.block_id, body.note))


@router.patch('/{paper_id}/{bookmark_id}')
def update_bookmark(paper_id: str, bookmark_id: str, body: BookmarkUpdate, request: Request):
    return operate(lambda: request.app.state.library.bookmarks.update(paper_id, bookmark_id, body.model_dump(exclude_unset=True)))


@router.delete('/{paper_id}/{bookmark_id}', status_code=204)
def delete_bookmark(paper_id: str, bookmark_id: str, request: Request):
    operate(lambda: request.app.state.library.bookmarks.delete(paper_id, bookmark_id))
    return Response(status_code=204)
