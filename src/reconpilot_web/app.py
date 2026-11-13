"""The FastAPI application."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import sessionmaker

from reconpilot_web import auth, db
from reconpilot_web.config import Settings
from reconpilot_web.models import assert_instance_mode

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


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
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(auth.router)
    return app
