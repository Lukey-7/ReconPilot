"""The engine's AI response cache, held in the ``ai_cache`` table.

``DbResponseCache`` has the engine ``ResponseCache``'s ``get(key)`` and
``put(key, provider, model, response)``, so ``ai.assist_cases`` uses it
unchanged. Keys are the engine's prompt hashes, which already include the
prompt version, provider, model and effort, so a cached answer is only ever
reused for exactly the same question to exactly the same model.

The engine fetches answers on a thread pool, so access to the session is
serialised with a lock. With ``autocommit`` each ``put`` commits at once: the
runner gives the cache a session of its own, so an answer that has been paid
for is kept even if the run that asked for it fails and is retried.
"""

from __future__ import annotations

import threading

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reconpilot.ai import PROMPT_VERSION
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
