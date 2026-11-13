"""Analyst review of suggested causes, with role checks and four-eyes sign-off.

Sign-off (NAV release) also requires that every material case has been
approved or reclassified, and that escalated cases were decided by an approver.
"""

from __future__ import annotations

from enum import Enum

from reconpilot.audit import AuditLog
from reconpilot.impact import blocking_cases, sort_by_impact
from reconpilot.models import Case, Category


class Role(str, Enum):
    ANALYST = "analyst"
    APPROVER = "approver"
    VIEWER = "viewer"


class PermissionDenied(Exception):
    pass


class ReviewError(Exception):
    pass


_CAN_DECIDE = {Role.ANALYST, Role.APPROVER}
_CAN_SIGN_OFF = {Role.APPROVER}


class ReviewSession:
    def __init__(self, cases: list[Case], audit: AuditLog, user: str, role: Role | str):
        self.cases = {c.case_id: c for c in cases}
        self.audit = audit
        self.user = user
        self.role = Role(role)

    def _require(self, allowed: set[Role], action: str) -> None:
        if self.role not in allowed:
            self.audit.append(self.user, self.role.value, "PERMISSION_DENIED", {"attempted": action})
            raise PermissionDenied(f"{self.user} ({self.role.value}) may not {action}")

    def _case(self, case_id: str) -> Case:
        try:
            return self.cases[case_id]
        except KeyError:
            raise ReviewError(f"no case {case_id}") from None

    def _decide(self, case_id: str, status: str, final: Category | None, note: str) -> Case:
        self._require(_CAN_DECIDE, "review cases")
        case = self._case(case_id)
        before = {"status": case.status, "final_category": case.final_category}
        case.status = status
        case.final_category = final
        case.reviewed_by = self.user
        case.reviewed_role = self.role.value
        case.review_note = note
        self.audit.append(
            self.user,
            self.role.value,
            f"CASE_{status}",
            {
                "case_id": case_id,
                "suggested": case.category.value,
                "final": final.value if final else None,
                "before": {k: (v.value if isinstance(v, Category) else v) for k, v in before.items()},
                "note": note,
                "material": case.material,
                "escalated": case.escalated,
            },
        )
        return case

    def approve(self, case_id: str, note: str = "") -> Case:
        case = self._case(case_id)
        return self._decide(case_id, "APPROVED", case.category, note)

    def reject(self, case_id: str, note: str = "") -> Case:
        if not note:
            raise ReviewError("a rejection needs a note explaining why")
        return self._decide(case_id, "REJECTED", None, note)

    def reclassify(self, case_id: str, category: Category | str, note: str = "") -> Case:
        return self._decide(case_id, "RECLASSIFIED", Category(category), note)

    def pending(self) -> list[Case]:
        """Cases awaiting a decision, largest NAV impact first."""
        return sort_by_impact([c for c in self.cases.values() if c.status == "PENDING"])

    def queue(self) -> list[Case]:
        """All open cases, largest NAV impact first."""
        return sort_by_impact([c for c in self.cases.values() if not c.cleared_on])

    def sign_off(self) -> dict:
        """Close the day. Needs an approver who reviewed none of the cases themselves."""
        self._require(_CAN_SIGN_OFF, "sign off the day")
        if self.pending():
            raise ReviewError(f"{len(self.pending())} case(s) still pending review")
        blocked = blocking_cases(list(self.cases.values()))
        if blocked:
            self.audit.append(self.user, self.role.value, "SIGN_OFF_BLOCKED",
                              {"reason": "material cases not approved", "cases": [c.case_id for c in blocked]})
            raise ReviewError(
                f"NAV release blocked: {len(blocked)} material case(s) not approved "
                f"({', '.join(c.case_id for c in blocked)})"
            )
        unconfirmed = [c.case_id for c in self.cases.values()
                       if c.escalated and not c.cleared_on and c.reviewed_role != Role.APPROVER.value]
        if unconfirmed:
            self.audit.append(self.user, self.role.value, "SIGN_OFF_BLOCKED",
                              {"reason": "escalated cases need an approver decision", "cases": unconfirmed})
            raise ReviewError(
                f"{len(unconfirmed)} escalated case(s) need a decision by an approver: {', '.join(unconfirmed)}"
            )
        own = [c.case_id for c in self.cases.values() if c.reviewed_by == self.user]
        if own:
            self.audit.append(self.user, self.role.value, "SIGN_OFF_BLOCKED", {"reason": "four-eyes", "cases": own})
            raise PermissionDenied(
                f"{self.user} reviewed {len(own)} case(s) and cannot also sign off (four-eyes rule)"
            )
        return self.audit.append(self.user, self.role.value, "DAY_SIGNED_OFF", {"cases": len(self.cases)})
