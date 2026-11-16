"""The FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response
from sqlalchemy.orm import sessionmaker

from reconpilot_web import (
    admin,
    auditviewer,
    auth,
    cases,
    days,
    daytrail,
    demo,
    db,
    funds,
    mi,
    overview,
    preferences,
    release,
)
from reconpilot_web.aicache import load_demo_cache
from reconpilot_web.config import Settings
from reconpilot_web.models import assert_instance_mode

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def add_security_headers(request: Request, response: Response) -> Response:
    """Set the security headers (and ``no-store`` on API routes) unless a route set its own."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def mount_web(app: FastAPI, dist: Path) -> None:
    """Serve the built front end in ``dist``: its files, and ``index.html`` for any other page.

    Registered after the API, so ``/api`` routes win; an unknown ``/api`` path is
    still a JSON 404, and so is a missing file (a path whose last part has a dot).
    Hashed assets are cached for good; ``index.html`` is revalidated every time.
    """
    root = dist.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def front_end(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        if path:
            candidate = (root / path).resolve()
            if root in candidate.parents and candidate.is_file():
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(404, "Not Found")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings, web_dist: Path | None = None) -> FastAPI:
    """Build the app for ``settings``, serving the built front end in ``web_dist`` if given.

    Refuses (``RuntimeError``) a database written for the other instance mode, so
    a demo instance can never open real data or the other way round. A demo instance
    loads the demo's pre-filled AI cache into its database.
    """
    from reconpilot_web.cli import database_urls

    url, _ = database_urls(settings)
    engine = db.make_engine(url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            assert_instance_mode(session, settings.mode)
        if settings.mode == "demo":  # the demo's AI answers, built in advance (spec section 11)
            with session_factory() as session, session.begin():
                load_demo_cache(session)
    except BaseException:
        engine.dispose()
        raise

    app = FastAPI(
        title="ReconPilot",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        dependencies=[Depends(auth.csrf_protect)],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        return add_security_headers(request, await call_next(request))

    # An unhandled exception is answered by Starlette's outermost error layer, which
    # the middleware above never sees; this handler gives that 500 the headers too.
    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        response = JSONResponse({"detail": "Internal server error."}, status_code=500)
        return add_security_headers(request, response)

    app.include_router(auth.router)
    app.include_router(preferences.router)
    app.include_router(funds.router)
    app.include_router(days.router)
    app.include_router(days.jobs_router)
    app.include_router(cases.router)
    app.include_router(release.router)
    app.include_router(overview.router)
    app.include_router(daytrail.router)
    app.include_router(mi.router)
    app.include_router(auditviewer.router)
    app.include_router(demo.router)
    app.include_router(admin.router)
    if web_dist is not None:
        mount_web(app, web_dist)
    return app
