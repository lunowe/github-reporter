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
from app.redis_client import init_redis, close_redis
from app.routes.health import router as health_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.repos import router as repos_router
from app.routes.dashboard import router as dashboard_router
from app.routes.access_codes import router as access_codes_router
from app.routes.invites import router as invites_router
from app.routes.admin import router as admin_router
from app.routes.automations import router as automations_router

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
    init_redis(settings.redis_url)

    from app.services.chat_store import ensure_indexes as chat_indexes
    from app.services.dashboard_cache import ensure_indexes as dashboard_indexes
    from app.services.user_service import ensure_indexes as user_indexes, migrate_existing_users
    from app.services.access_code_service import ensure_indexes as access_code_indexes
    from app.services.invite_service import ensure_indexes as invite_indexes
    from app.services.automations_store import ensure_indexes as automations_indexes
    from app.services.scheduler import start_scheduler, shutdown_scheduler
    from app.services import stream_manager

    await chat_indexes()
    await dashboard_indexes()
    await user_indexes()
    await access_code_indexes()
    await invite_indexes()
    await automations_indexes()

    # Migrate existing users to have activation fields
    await migrate_existing_users()

    # Boot the automations scheduler and hydrate jobs from DB
    await start_scheduler()

    # Boot the chat run cancel subscriber (Redis pub/sub listener)
    await stream_manager.start_cancel_subscriber()

    logging.getLogger(__name__).info("MongoDB connected: %s", settings.mongodb_db_name)
    yield
    # Shutdown — stop accepting new runs, cancel any locally-owned runs so their
    # `finally` blocks fire and flush partial messages to Mongo, then tear down.
    await stream_manager.shutdown_local_runs()
    await stream_manager.stop_cancel_subscriber()
    await shutdown_scheduler()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GitHub Reporter",
        description="Agentic tool to query GitHub repos for project status reports.",
        version="0.3.0",
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
    app.include_router(access_codes_router)
    app.include_router(invites_router)
    app.include_router(admin_router)
    app.include_router(automations_router)

    return app


app = create_app()
