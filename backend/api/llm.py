from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..llm.settings import SettingsConflict, SettingsError, validate_settings
from ..llm.client import LLMError


@contextmanager
def settings_errors():
    try:
        yield
    except SettingsConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except SettingsError as exc:
        raise HTTPException(400, str(exc)) from exc


router = APIRouter(prefix='/api/llm', tags=['llm'])


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=200)
    api_key: SecretStr | None = None  # Omitted or blank values preserve the saved key.
    revision: str
    translate_references: bool | None = Field(default=None, strict=True)
    auto_translate: bool | None = Field(default=None, strict=True)
    concurrency: int | None = Field(default=None, strict=True, ge=1, le=30)
    translation_batch_size: int | None = Field(default=None, strict=True, ge=1, le=20)
    index_batch_size: int | None = Field(default=None, strict=True, ge=1, le=16)
    embedding_threads: int | None = Field(default=None, strict=True, ge=1, le=16)
    model_idle_minutes: int | None = Field(default=None, strict=True, ge=1, le=60)


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    input: str = Field(min_length=1, max_length=1_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=65536)


@router.get('/settings')
def get_settings(request: Request):
    with settings_errors():
        return request.app.state.llm_settings.public()


@router.put('/settings')
def save_settings(body: SettingsUpdate, request: Request):
    with settings_errors():
        settings = request.app.state.llm_settings.update(
            body.base_url, body.model,
            body.api_key.get_secret_value() if body.api_key is not None else None,
            body.revision, **body.model_dump(exclude={'base_url', 'model', 'api_key', 'revision'}),
        )
        request.app.state.library.configure(settings)
        return settings


@router.get('/settings/api-key')
def get_api_key(request: Request, revision: str):
    with settings_errors():
        settings, current_revision = request.app.state.llm_settings.read()
        if revision != current_revision:
            raise HTTPException(409, '设置已被修改，请重新打开设置后再查看 API Key。')
        return JSONResponse({'api_key': settings['api_key']}, headers={'Cache-Control': 'no-store, private'})


@router.post('/responses')
async def responses(body: ResponsesRequest, request: Request):
    try:
        with settings_errors():
            settings, _ = request.app.state.llm_settings.read()
            settings = validate_settings(settings)
            transport = request.app.state.llm_client
            response = await transport.open(settings, body.model_dump(exclude_none=True))
    except LLMError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return StreamingResponse(transport.stream(response, settings['api_key']),
                             media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
