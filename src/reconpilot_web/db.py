"""SQLAlchemy engine, session factory and declarative base."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(expire_on_commit=False)


def sqlalchemy_url(url: str) -> str:
    """Use the psycopg 3 driver for plain ``postgresql://`` (or ``postgres://``) URLs."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str) -> Engine:
    return create_engine(sqlalchemy_url(url), pool_pre_ping=True)


def configure(url: str) -> Engine:
    """Bind ``SessionLocal`` to a new engine for ``url`` and return the engine."""
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)
    return engine
