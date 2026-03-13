from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import SessionLocal
from app.database import init_db
from app.routers import admin
from app.routers import presentation
from app.routers import public
from app.services.contest import ensure_default_event
from app.services.contest import ensure_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_storage(settings)
    init_db()
    with SessionLocal() as session:
        ensure_default_event(session, settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_storage(settings)
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.mount("/uploads", StaticFiles(directory=settings.upload_path), name="uploads")
    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(presentation.router)
    return app


app = create_app()
