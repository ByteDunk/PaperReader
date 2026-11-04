from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging

from fastapi import FastAPI

from .api.papers import router
from .papers.library import Library
from .api.llm import router as llm_router
from .llm.settings import SettingsStore, ENV_PATH
from .llm.client import ResponsesClient
from .llm.runs import RunStore
from .papers.translation import TranslationService
from .rag.service import RagService
from .api.search import router as search_router
from .api.assistant import router as assistant_router
from .api.bookmarks import router as bookmarks_router


def create_app(data_dir=None, env_path=None):
    @asynccontextmanager
    async def lifespan(application):
        library = Library(data_dir or Path(__file__).parent / 'data' / 'library')
        application.state.library = library
        maintenance = None
        stop_maintenance = asyncio.Event()
        try:
            library.translations = TranslationService(library, application.state.llm_settings,
                                                      application.state.llm_client, asyncio.get_running_loop())
            library.rag = RagService(library)
            library.configure(application.state.llm_settings.resources())
            await asyncio.to_thread(library.resume)

            async def maintain():
                while not stop_maintenance.is_set():
                    try:
                        await asyncio.wait_for(stop_maintenance.wait(), timeout=15)
                        return
                    except TimeoutError:
                        pass
                    try:
                        await asyncio.to_thread(library.maintain, application.state.llm_settings.resources())
                    except Exception:
                        logging.getLogger(__name__).exception('Resource maintenance failed')

            maintenance = asyncio.create_task(maintain())
            yield
        finally:
            await application.state.assistant_runs.shutdown()
            stop_maintenance.set()
            if maintenance:
                await maintenance
            try:
                await library.aclose()
            finally:
                await application.state.llm_client.shutdown()

    application = FastAPI(lifespan=lifespan)
    application.state.llm_settings = SettingsStore(env_path if env_path is not None else ENV_PATH)
    application.state.llm_client = ResponsesClient()
    application.state.assistant_runs = RunStore()
    for api in (router, llm_router, search_router, assistant_router, bookmarks_router):
        application.include_router(api)

    return application
