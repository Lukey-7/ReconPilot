"""One business day through the whole pipeline, shared by the CLI and the evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field

from reconpilot.ai import LLMClient, ResponseCache, assist_cases
from reconpilot.audit import AuditLog
from reconpilot.impact import apply_impacts, release_check, sort_by_impact
from reconpilot.ledger import LifecycleSettings, roll_forward
from reconpilot.matching import ReconResult, Tolerances, reconcile
from reconpilot.models import Case, DayData
from reconpilot.nav import Check, NavResult, compute_nav, run_checks
from reconpilot.triage import triage


@dataclass
class DayResult:
    day: DayData
    recon: ReconResult
    nav: NavResult
    checks: list[Check]
    open_cases: list[Case]  # today's queue, largest NAV impact first
    cleared: list[Case] = field(default_factory=list)  # cleared automatically today


def run_day(
    day: DayData,
    prior_open: list[Case] | None = None,
    settings: LifecycleSettings | None = None,
    tolerances: Tolerances | None = None,
    use_ai: bool = False,
    ai_client: LLMClient | None = None,
    ai_cache: ResponseCache | None = None,
    audit: AuditLog | None = None,
    actor: str = "system",
    role: str = "analyst",
    max_workers: int = 8,
) -> DayResult:
    """Reconcile, triage, (optionally) ask the AI, value, check and roll the ledger forward.

    ``day.carried_book_items`` and ``day.carried_custodian_lines`` should already
    hold the previous day's open items when running a sequence.
    """
    settings = settings or LifecycleSettings()
    recon = reconcile(day, tolerances)
    cases = triage(day, recon)
    if use_ai:
        assist_cases(day, recon, cases, ai_client, audit=audit, actor=actor, role=role,
                     cache=ai_cache, max_workers=max_workers)
    nav = compute_nav(day)
    checks = run_checks(day, nav, recon)
    cases = apply_impacts(day, recon, cases, nav, settings.materiality_bp)
    open_cases, cleared = roll_forward(prior_open or [], cases, recon, day.as_of, settings, audit, actor, role)
    open_cases = sort_by_impact(open_cases)
    checks.append(release_check(open_cases, settings.materiality_bp))
    return DayResult(day, recon, nav, checks, open_cases, cleared)
