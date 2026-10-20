"""DeepDive application package (Flask-style layout, FastAPI underneath).

`create_app()` is the application factory, like Flask's. Routers in app/routes/ play
the role of blueprints: `pages` serves the HTML UI, the `api_*` routers serve JSON.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

BASE_DIR = Path(__file__).parent

# Pages load only our own scripts and Google Fonts. Inline scripts are allowed for the two tiny
# ones in base.html (theme before first paint, icon sprite path); API text is never inserted as
# HTML (el() uses textContent), which is the real XSS defence.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors {ancestors}")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
API_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")  # Swagger UI loads its own CDN assets


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
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # FRAME_ANCESTORS (e.g. "https://huggingface.co"): the only sites allowed to show the app in
        # a frame. Hugging Face Spaces shows apps inside an iframe on huggingface.co. Default: none.
        allowed = get_settings().frame_ancestors.split()
        for name, value in SECURITY_HEADERS.items():
            if name == "X-Frame-Options" and allowed:
                continue  # X-Frame-Options cannot name another site; the CSP rule below does
            response.headers.setdefault(name, value)
        if not request.url.path.startswith(API_DOC_PATHS):
            ancestors = " ".join(["'self'", *allowed]) if allowed else "'none'"
            response.headers.setdefault("Content-Security-Policy", CSP.format(ancestors=ancestors))
        if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(health.router, prefix="/api")
    app.include_router(api_runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(api_files.router, prefix="/api/files", tags=["files"])
    app.include_router(dev.router)
    return app
