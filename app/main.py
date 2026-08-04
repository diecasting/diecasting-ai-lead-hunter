"""FastAPI application entrypoint for diecasting-ai-lead-hunter."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import leads as leads_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: create tables on startup. Production should use migrations.
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # pragma: no cover - depends on DB availability
        print(f"[startup] Could not create tables (is the database up?): {exc}")
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads_router.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/", tags=["root"])
def root():
    return {"app": settings.app_name, "docs": "/docs", "openapi": "/openapi.json"}
