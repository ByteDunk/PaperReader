from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..rag.service import IndexNotReady
from .papers import paper_errors

router = APIRouter(prefix='/api', tags=['search'])


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    scope: Literal['paper', 'all'] = 'paper'
    paper_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    limit: int = Field(default=12, ge=1, le=30)

    @model_validator(mode='after')
    def validate_query(self):
        self.query = self.query.strip()
        if not self.query:
            raise ValueError('请输入搜索内容。')
        if self.scope == 'paper' and not self.paper_id:
            raise ValueError('请选择当前论文。')
        return self


@router.post('/search')
def search(body: SearchRequest, request: Request):
    try:
        with paper_errors(conflict=IndexNotReady):
            return request.app.state.library.rag.search(body.query, body.scope, body.paper_id, body.limit)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post('/papers/{paper_id}/index', status_code=202)
def rebuild_index(paper_id: str, request: Request):
    with paper_errors(conflict=IndexNotReady):
        return request.app.state.library.rag.retry(paper_id)
