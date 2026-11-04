from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..llm.agent import agent_stream
from ..llm.runs import RunConflict
from ..llm.settings import validate_settings
from .papers import paper_errors
from .llm import settings_errors

router = APIRouter(prefix='/api/assistant', tags=['assistant'])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=20000)


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paper_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    page: int = Field(default=1, ge=1, le=100000)
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    request_id: str = Field(max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


def run_response(run, after=0):
    return StreamingResponse(run.events(after), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.post('/chat')
async def chat(body: AgentRequest, request: Request):
    state = request.app.state
    if body.messages[-1].role != 'user' or sum(len(m.content) for m in body.messages) > 100000:
        raise HTTPException(400, '对话必须以用户问题结尾，且总长度不能超过 100000 字符。')
    with settings_errors(), paper_errors(conflict=()):
        settings, _ = state.llm_settings.read()
        settings = validate_settings(settings)
        if not settings['api_key']:
            raise HTTPException(400, '请先在 API 设置中填写并保存 API Key。')
        state.library.read(body.paper_id)
    try:
        run = state.assistant_runs.start(body, lambda: agent_stream(state.llm_client, settings, state.library, body))
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return run_response(run)


@router.get('/runs/{run_id}/events')
async def reconnect(run_id: str, request: Request, after: int = 0):
    run = request.app.state.assistant_runs.get(run_id)
    if run is None:
        raise HTTPException(404, '生成任务已过期或后端已重启，请重新生成。')
    if not 0 <= after <= len(run.frames):
        raise HTTPException(400, '无效的重连位置。')
    return run_response(run, after)


@router.delete('/runs/{run_id}')
async def stop(run_id: str, request: Request):
    run = request.app.state.assistant_runs.get(run_id)
    if run is not None:
        await run.cancel()
    return {'stopped': True}
