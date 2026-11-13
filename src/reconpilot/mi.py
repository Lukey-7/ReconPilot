"""Management information: the morning view of breaks across days.

Built from the per-day ledger snapshots in a run directory. ``mi_rows`` gives
the same figures in tidy (long) form for Tableau or any other BI tool: one row
per date, metric, cause and age bucket.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reconpilot.impact import sort_by_impact
from reconpilot.ledger import BUCKETS, current_category, days_to_resolve
from reconpilot.models import Case, Category

ALL = "ALL"
MI_COLUMNS = ["as_of", "metric", "cause", "age_bucket", "value"]


@dataclass
class DaySummary:
    as_of: str
    open_cases: int
    new_cases: int
    cleared_cases: int
    material_open: int
    escalated_open: int
    sla_breaches_open: int
    aged_over_5: int
    open_nav_impact: float
    avg_days_to_resolve: float | None


@dataclass
class MI:
    as_of: str
    by_cause_age: dict[tuple[str, str], int] = field(default_factory=dict)
    impact_by_cause_age: dict[tuple[str, str], float] = field(default_factory=dict)
    resolve_by_cause: dict[str, tuple[int, float]] = field(default_factory=dict)  # cause -> (n, avg days)
    avg_days_to_resolve: float | None = None
    top_cases: list[Case] = field(default_factory=list)
    sla_breaches: list[Case] = field(default_factory=list)
    trend: list[DaySummary] = field(default_factory=list)

    @property
    def causes(self) -> list[str]:
        seen = {cause for cause, _ in self.by_cause_age}
        return [c.value for c in Category if c.value in seen]


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def summarise_day(as_of: str, ledger: list[Case]) -> DaySummary:
    open_cases = [c for c in ledger if not c.cleared_on]
    resolved = [d for c in ledger if (d := days_to_resolve(c)) is not None]
    return DaySummary(
        as_of=as_of,
        open_cases=len(open_cases),
        new_cases=sum(1 for c in ledger if c.first_seen == as_of),
        cleared_cases=sum(1 for c in ledger if c.cleared_on == as_of),
        material_open=sum(1 for c in open_cases if c.material),
        escalated_open=sum(1 for c in open_cases if c.escalated),
        sla_breaches_open=sum(1 for c in open_cases if c.sla_breached),
        aged_over_5=sum(1 for c in open_cases if c.age_bucket == ">5"),
        open_nav_impact=round(sum(c.nav_impact for c in open_cases), 2),
        avg_days_to_resolve=_avg(resolved),
    )


def build_mi(as_of: date | str, ledger: list[Case], history: dict[str, list[Case]] | None = None,
             trend_days: int = 20) -> MI:
    as_of = str(as_of)
    mi = MI(as_of=as_of)
    open_cases = [c for c in ledger if not c.cleared_on]
    for c in open_cases:
        key = (current_category(c).value, c.age_bucket)
        mi.by_cause_age[key] = mi.by_cause_age.get(key, 0) + 1
        mi.impact_by_cause_age[key] = round(mi.impact_by_cause_age.get(key, 0.0) + c.nav_impact, 2)

    per_cause: dict[str, list[int]] = defaultdict(list)
    for c in ledger:
        d = days_to_resolve(c)
        if d is not None:
            per_cause[current_category(c).value].append(d)
    mi.resolve_by_cause = {k: (len(v), _avg(v)) for k, v in per_cause.items()}
    mi.avg_days_to_resolve = _avg([d for v in per_cause.values() for d in v])
    mi.top_cases = sort_by_impact(open_cases)[:5]
    mi.sla_breaches = sorted((c for c in ledger if c.sla_breached),
                             key=lambda c: (bool(c.cleared_on), -c.age_days, c.case_id))

    history = dict(history or {})
    history[as_of] = ledger
    dates = sorted(d for d in history if d <= as_of)[-trend_days:]
    mi.trend = [summarise_day(d, history[d]) for d in dates]
    return mi


def mi_rows(history: dict[str, list[Case]]) -> list[dict]:
    """Tidy rows for every day in ``history`` (date -> that day's ledger)."""
    rows: list[dict] = []

    def add(as_of, metric, value, cause=ALL, bucket=ALL):
        rows.append({"as_of": as_of, "metric": metric, "cause": cause, "age_bucket": bucket, "value": value})

    for as_of in sorted(history):
        ledger = history[as_of]
        s = summarise_day(as_of, ledger)
        for metric in ("open_cases", "new_cases", "cleared_cases", "material_open", "escalated_open",
                       "sla_breaches_open", "aged_over_5", "open_nav_impact"):
            add(as_of, metric, getattr(s, metric))
        if s.avg_days_to_resolve is not None:
            add(as_of, "avg_days_to_resolve", s.avg_days_to_resolve)
        counts: dict[tuple[str, str], list[Case]] = defaultdict(list)
        for c in ledger:
            if not c.cleared_on:
                counts[(current_category(c).value, c.age_bucket)].append(c)
        for (cause, bucket), cases in sorted(counts.items()):
            add(as_of, "open_cases", len(cases), cause, bucket)
            add(as_of, "open_nav_impact", round(sum(c.nav_impact for c in cases), 2), cause, bucket)
        for c in ledger:
            if c.cleared_on == as_of:
                add(as_of, "cleared_cases", 1, current_category(c).value, c.age_bucket)
    return rows


def write_mi_csv(path: str | Path, history: dict[str, list[Case]]) -> Path:
    out = Path(path)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MI_COLUMNS)
        w.writeheader()
        w.writerows(mi_rows(history))
    return out


__all__ = ["MI", "BUCKETS", "DaySummary", "build_mi", "mi_rows", "summarise_day", "write_mi_csv"]
