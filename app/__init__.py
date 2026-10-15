"""DeepDive application package (Flask-style layout, FastAPI underneath).

`create_app()` is the application factory, like Flask's. Routers in app/routes/ play
the role of blueprints: `pages` serves the HTML UI, the `api_*` routers serve JSON.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from app.db.session import init_db
    from app.routes import api_files, api_runs, dev, health, pages

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title="DeepDive",
        description="Self-verifying multi-agent research analyst. All LLM calls go through Mesh API.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(health.router, prefix="/api")
    app.include_router(api_runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(api_files.router, prefix="/api/files", tags=["files"])
    app.include_router(dev.router)
    return app
