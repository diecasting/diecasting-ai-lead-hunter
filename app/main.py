"""FastAPI application entrypoint for diecasting-ai-lead-hunter."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import crm as crm_router
from app.api import crm_models as crm_models_router
from app.api import crawl as crawl_router
from app.api import discovery as discovery_router
from app.api import email as email_router
from app.api import contacts as contacts_router
from app.api import agent as agent_router
from app.api import campaign as campaign_router
from app.api import export as export_router
from app.api import reply as reply_router
from app.api import pipeline as pipeline_router
from app.api import outreach as outreach_router
from app.api import quora as quora_router
from app.api import search as search_router
from app.config import settings
from app.database import Base, engine
from app.routers import leads as leads_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite (local dev / tests): create tables directly.
    # PostgreSQL (production): tables are managed by `alembic upgrade head`
    # (see migrations/) and run from the Docker entrypoint / scripts/init_db.py.
    if settings.sqlalchemy_database_uri.startswith("sqlite"):
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as exc:  # pragma: no cover - depends on DB availability
            print(f"[startup] Could not create tables: {exc}")
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads_router.router)
app.include_router(crawl_router.router)
app.include_router(search_router.router)
app.include_router(export_router.router)
app.include_router(outreach_router.router)
app.include_router(crm_router.router)
app.include_router(crm_models_router.router)
app.include_router(discovery_router.router)
app.include_router(email_router.router)
app.include_router(contacts_router.router)
app.include_router(agent_router.router)
app.include_router(campaign_router.router)
app.include_router(reply_router.router)
app.include_router(pipeline_router.router)
app.include_router(quora_router.quora_router)
app.include_router(quora_router.seo_router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/", tags=["root"])
def root():
    return {"app": settings.app_name, "docs": "/docs", "openapi": "/openapi.json"}
