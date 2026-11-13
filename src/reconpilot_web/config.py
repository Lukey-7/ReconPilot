"""Settings for the web application, read from environment variables.

Variables:

``RP_DATABASE_URL``
    The database the API and worker use. Empty means the embedded development
    database in ``RP_DATA_DIR`` (see ``devdb``).
``RP_MIGRATION_DATABASE_URL``
    The database role that owns the schema and runs migrations. Defaults to
    ``RP_DATABASE_URL``.
``RP_MODE``
    ``real`` (default) or ``demo``. A database is written once with its mode and
    an instance refuses to start against a database of the other mode.
``RP_COOKIE_SECURE``
    ``1`` to mark session cookies ``Secure`` (always, behind HTTPS).
``RP_DATA_DIR``
    Folder for local state: the embedded database and the AI cache. Default ``.rp_data``.
``RP_AI_CACHE_DIR``
    Folder for cached AI responses. Default ``<RP_DATA_DIR>/ai_cache``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

Mode = Literal["real", "demo"]
MODES: tuple[str, ...] = ("real", "demo")

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    migration_database_url: str
    mode: Mode
    cookie_secure: bool
    data_dir: Path
    ai_cache_dir: Path


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """Build ``Settings`` from ``env``. Raises ``ValueError`` for an unknown mode."""
    mode = (env.get("RP_MODE") or "real").strip().lower()
    if mode not in MODES:
        raise ValueError(f"RP_MODE must be one of {', '.join(MODES)}, not {mode!r}")
    database_url = (env.get("RP_DATABASE_URL") or "").strip()
    migration_url = (env.get("RP_MIGRATION_DATABASE_URL") or "").strip() or database_url
    data_dir = Path(env.get("RP_DATA_DIR") or ".rp_data")
    ai_cache_dir = Path(env.get("RP_AI_CACHE_DIR") or data_dir / "ai_cache")
    return Settings(
        database_url=database_url,
        migration_database_url=migration_url,
        mode=cast(Mode, mode),
        cookie_secure=_flag(env.get("RP_COOKIE_SECURE")),
        data_dir=data_dir,
        ai_cache_dir=ai_cache_dir,
    )
