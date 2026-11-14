"""What each user prefers to see: for now, the fund they last chose to work.

The fund selector stores the user's choice here, so it follows them from one
browser or desk to another, and every user keeps their own. A fund opened from
a shared link is not stored; only a choice made in the selector is. A
preference is a convenience, not a control, so changing it is not audited.

    GET /api/auth/me/preferences        -> {"fund": "GEF1" | null}
    PUT /api/auth/me/preferences {"fund": "INC2" | null}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reconpilot_web.auth import current_user, get_db
from reconpilot_web.funds import get_fund
from reconpilot_web.models import Fund, User

router = APIRouter(prefix="/api/auth/me", tags=["auth"])


class PreferencesUpdate(BaseModel):
    fund: str | None = None


def preferences_payload(db: Session, user: User) -> dict[str, Any]:
    fund = db.get(Fund, user.preferred_fund_id) if user.preferred_fund_id is not None else None
    return {"fund": fund.code if fund is not None else None}


@router.get("/preferences")
def read_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return preferences_payload(db, user)


@router.put("/preferences")
def update_preferences(
    body: PreferencesUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Store the user's fund (404 for a fund that does not exist; ``null`` clears it)."""
    user.preferred_fund_id = get_fund(db, body.fund).id if body.fund else None
    db.commit()
    return preferences_payload(db, user)
