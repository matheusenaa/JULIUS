import logging
from datetime import UTC
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    accounts,
    ai,
    auth,
    categories,
    data,
    debts,
    documents,
    overview,
    planning,
    recurrences,
    sync,
    transactions,
)
from app.config import get_settings
from app.db import SessionLocal
from app.errors import install_error_handlers
from app.security.middleware import SecurityMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="JULIUS",
        version="0.1.0",
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(SecurityMiddleware)
    if not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    routers = (
        auth,
        accounts,
        categories,
        transactions,
        recurrences,
        overview,
        planning,
        ai,
        data,
        debts,
        documents,
        sync,
    )
    for module in routers:
        app.include_router(module.router)

    @app.get("/api/health", tags=["infra"])
    def health():
        from datetime import datetime

        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "app_env": settings.app_env,
            "ai_provider": settings.ai_provider,
            "timezone": settings.timezone,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Em produção o FastAPI serve o PWA compilado: mesma origem, sem CORS."""
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise StarletteHTTPException(404)
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
