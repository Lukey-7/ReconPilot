"""The engine's AI response cache, held in the ``ai_cache`` table.

``DbResponseCache`` has the engine ``ResponseCache``'s ``get(key)`` and
``put(key, provider, model, response)``, so ``ai.assist_cases`` uses it
unchanged. Keys are the engine's prompt hashes, which already include the
prompt version, provider, model and effort, so a cached answer is only ever
reused for exactly the same question to exactly the same model.

The demo (spec section 11) answers from a cache filled in advance: the file
``demo_ai_cache.json`` beside this module holds the real AI's responses for the
demo's fixed seed (responses only, never a key), written by
``scripts/build_demo_ai_cache.py``. ``load_demo_cache`` copies it into the
``ai_cache`` table when a demo instance starts, and ``CacheOnlyClient`` stands in
for the provider with the same provider, model and effort, so its prompt hashes
find those responses; a question it has no answer for falls back to the rules.

The engine fetches answers on a thread pool, so access to the session is
serialised with a lock. With ``autocommit`` each ``put`` commits at once: the
runner gives the cache a session of its own, so an answer that has been paid
for is kept even if the run that asked for it fails and is retried.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reconpilot.ai import PROMPT_VERSION, AIError
from reconpilot_web.models import AICacheEntry


class DbResponseCache:
    def __init__(self, session: Session, autocommit: bool = False):
        self.session = session
        self.autocommit = autocommit
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self.session.execute(
                select(AICacheEntry.response).where(AICacheEntry.key == key)
            ).scalar_one_or_none()

    def put(self, key: str, provider: str, model: str, response: str) -> None:
        with self._lock:
            self.session.execute(
                insert(AICacheEntry)
                .values(key=key, provider=provider, model=model, prompt_version=PROMPT_VERSION,
                        response=response)
                .on_conflict_do_nothing(index_elements=["key"])
            )
            if self.autocommit:
                self.session.commit()
            else:
                self.session.flush()


# --------------------------------------------------------------------------- the demo's cache

DEMO_CACHE_FILE = Path(__file__).resolve().parent / "demo_ai_cache.json"
CACHE_MISS = "not in the demo's AI cache, so the rules' answer stands"


@dataclass
class CacheOnlyClient:
    """An AI "client" that never calls a provider: every answer must come from the cache.

    It carries the provider, model and effort the cache was built with, so the engine's
    prompt hashes match; ``complete`` is reached only on a miss and raises ``AIError``,
    which the engine turns into its fallback to the rules.
    """

    provider: str
    model: str
    effort: str = "medium"

    def complete(self, system: str, user: str) -> str:
        raise AIError(CACHE_MISS)


def read_demo_cache(path: Path = DEMO_CACHE_FILE) -> dict[str, Any] | None:
    """The demo cache file as written by the build script, or ``None`` when there is none."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("responses"), dict):
        raise ValueError(f"{path} is not a demo AI cache")
    return data


def demo_client(path: Path = DEMO_CACHE_FILE) -> CacheOnlyClient | None:
    """The cache-only client for the demo cache in ``path``, or ``None`` without one."""
    data = read_demo_cache(path)
    if data is None:
        return None
    return CacheOnlyClient(provider=data["provider"], model=data["model"], effort=data.get("effort", "medium"))


def load_demo_cache(session: Session, path: Path = DEMO_CACHE_FILE) -> int:
    """Copy the demo cache's responses into ``ai_cache`` (existing keys are kept); how many it holds.

    In ``session``'s transaction; the caller commits.
    """
    data = read_demo_cache(path)
    if data is None:
        return 0
    rows = [
        {"key": key, "provider": data["provider"], "model": data["model"],
         "prompt_version": data.get("prompt_version", ""), "response": response}
        for key, response in data["responses"].items()
    ]
    if rows:
        session.execute(insert(AICacheEntry).values(rows).on_conflict_do_nothing(index_elements=["key"]))
    return len(rows)
