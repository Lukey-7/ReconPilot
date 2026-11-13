"""The FastAPI application."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response
from sqlalchemy.orm import sessionmaker

from reconpilot_web import auth, cases, days, db, funds
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


def create_app(settings: Settings) -> FastAPI:
    """Build the app for ``settings``.

    Refuses (``RuntimeError``) a database written for the other instance mode, so
    a demo instance can never open real data or the other way round.
    """
    from reconpilot_web.cli import database_urls

    url, _ = database_urls(settings)
    engine = db.make_engine(url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            assert_instance_mode(session, settings.mode)
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
    app.include_router(funds.router)
    app.include_router(days.router)
    app.include_router(days.jobs_router)
    app.include_router(cases.router)
    return app
