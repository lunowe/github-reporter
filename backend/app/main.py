# app/main.py
"""
GitHub Reporter – FastAPI entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routes.health import router as health_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.repos import router as repos_router
from app.routes.dashboard import router as dashboard_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    init_db(settings.mongodb_url, settings.mongodb_db_name)

    from app.services.chat_store import ensure_indexes as chat_indexes
    from app.services.dashboard_cache import ensure_indexes as dashboard_indexes
    from app.services.user_service import ensure_indexes as user_indexes
    await chat_indexes()
    await dashboard_indexes()
    await user_indexes()

    logging.getLogger(__name__).info("MongoDB connected: %s", settings.mongodb_db_name)
    yield
    # Shutdown (motor cleans up automatically)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GitHub Reporter",
        description="Agentic tool to query GitHub repos for project status reports.",
        version="0.2.0",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(repos_router)
    app.include_router(dashboard_router)

    return app


app = create_app()
