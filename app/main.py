from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.repositories import get_repository
from app.routers import admin
from app.routers import presentation
from app.routers import public
from app.services.contest import get_event
from app.storage import get_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    storage = get_storage()
    storage.ensure_ready()
    if settings.data_backend.lower() == "sqlite":
        init_db()
    repository = get_repository()
    get_event(repository, settings)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(presentation.router)
    return app


settings = get_settings()
app = create_app()
