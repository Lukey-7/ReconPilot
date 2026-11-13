"""Score the pipeline against breaks planted by the generator.

For each planted break we ask two questions: did a case get raised on that
security (detection), and was the suggested cause right (classification)?
Cases raised on securities where nothing was planted are false alarms.

With an AI client, the cause scored is the AI's suggestion when it passed the
guardrails, and the rule-based one when the case fell back. Detection does not
change: the AI never raises or closes cases, only explains them.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from reconpilot.ai import LLMClient, ResponseCache, assist_cases
from reconpilot.audit import AuditLog
from reconpilot.generator import GeneratorConfig, generate_day
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE, Case, Category, PlantedBreak
from reconpilot.triage import triage


@dataclass
class EvalResult:
    days: int
    label: str = "Rules only"
    planted: int = 0
    detected: int = 0
    correct: int = 0
    cases: int = 0
    false_alarms: int = 0
    per_category: dict[Category, Counter] = field(default_factory=dict)
    confusion: Counter = field(default_factory=Counter)  # (planted, suggested) -> count
    ai_calls: int = 0
    ai_accepted: int = 0
    ai_fallbacks: int = 0
    fallback_reasons: Counter = field(default_factory=Counter)
    disagreements: int = 0  # on cases matched to a planted break
    disagreements_ai_right: int = 0
    disagreements_rules_right: int = 0

    @property
    def detection_rate(self) -> float:
        return self.detected / self.planted if self.planted else 0.0

    @property
    def classification_accuracy(self) -> float:
        return self.correct / self.detected if self.detected else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / self.cases if self.cases else 0.0


def scored_category(case: Case) -> Category:
    if case.ai_status == "ACCEPTED" and case.ai_category is not None:
        return case.ai_category
    return case.category


def business_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def run_evaluation(
    days: int = 20,
    breaks_per_day: int = 10,
    seed: int = 42,
    difficulty: str = "standard",
    start: date = date(2026, 10, 1),
    ai_client: LLMClient | None = None,
    ai_cache: ResponseCache | None = None,
    audit: AuditLog | None = None,
    max_workers: int = 8,
) -> EvalResult:
    rng = random.Random(seed)
    schedule = [PLANTABLE[i % len(PLANTABLE)] for i in range(days * breaks_per_day)]
    rng.shuffle(schedule)
    label = f"AI ({ai_client.model})" if ai_client else "Rules only"
    result = EvalResult(days=days, label=label, per_category={c: Counter() for c in PLANTABLE})
    config = GeneratorConfig(difficulty=difficulty)

    for i, as_of in enumerate(business_days(start, days)):
        plants = schedule[i * breaks_per_day:(i + 1) * breaks_per_day]
        day, truth = generate_day(as_of, plants, seed=rng.randrange(2**31), config=config)
        recon = reconcile(day)
        cases = triage(day, recon)
        if ai_client is not None:
            assist_cases(day, recon, cases, ai_client, audit=audit, actor="evaluate",
                         cache=ai_cache, max_workers=max_workers)
            for c in cases:
                result.ai_calls += 1
                if c.ai_status == "ACCEPTED":
                    result.ai_accepted += 1
                else:
                    result.ai_fallbacks += 1
                    result.fallback_reasons[c.ai_fallback_reason.split(":")[0]] += 1
        by_security = {c.security_id: c for c in cases}
        planted_ids = {p.security_id for p in truth}

        result.cases += len(cases)
        result.false_alarms += sum(1 for c in cases if c.security_id not in planted_ids)
        for p in truth:
            stats = result.per_category[p.category]
            stats["planted"] += 1
            result.planted += 1
            case = by_security.get(p.security_id)
            if case is None:
                result.confusion[(p.category, None)] += 1
                continue
            stats["detected"] += 1
            result.detected += 1
            suggested = scored_category(case)
            result.confusion[(p.category, suggested)] += 1
            if suggested is p.category:
                stats["correct"] += 1
                result.correct += 1
            if case.ai_flag:
                result.disagreements += 1
                if case.ai_category is p.category:
                    result.disagreements_ai_right += 1
                elif case.category is p.category:
                    result.disagreements_rules_right += 1
    return result


def to_markdown(r: EvalResult, title: str = "Evaluation") -> str:
    lines = [
        f"## {title}",
        "",
        f"{r.days} business days, {r.planted} planted breaks, {r.cases} cases raised.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Breaks detected | {r.detected}/{r.planted} ({r.detection_rate:.1%}) |",
        f"| Cause correctly suggested (of detected) | {r.correct}/{r.detected} ({r.classification_accuracy:.1%}) |",
        f"| False alarms (cases with nothing planted) | {r.false_alarms}/{r.cases} ({r.false_alarm_rate:.1%}) |",
    ]
    if r.ai_calls:
        lines += [
            f"| AI responses accepted by the guardrails | {r.ai_accepted}/{r.ai_calls} |",
            f"| Fell back to rules | {r.ai_fallbacks}/{r.ai_calls} |",
            f"| AI disagreed with rules (planted cases) | {r.disagreements} "
            f"(AI right {r.disagreements_ai_right}, rules right {r.disagreements_rules_right}) |",
        ]
    lines += [
        "",
        "| Planted cause | Planted | Detected | Correct cause |",
        "|---|---|---|---|",
    ]
    for cat, s in r.per_category.items():
        lines.append(f"| {cat.value} | {s['planted']} | {s['detected']} | {s['correct']} |")

    cols = [*PLANTABLE, Category.UNKNOWN, None]
    lines += [
        "",
        "Confusion matrix (rows: planted, columns: suggested; MISSED = no case raised)",
        "",
        "| | " + " | ".join(c.value if c else "MISSED" for c in cols) + " |",
        "|---" * (len(cols) + 1) + "|",
    ]
    for cat in PLANTABLE:
        cells = [str(r.confusion.get((cat, c), 0)) for c in cols]
        lines.append(f"| {cat.value} | " + " | ".join(cells) + " |")
    if r.fallback_reasons:
        lines += ["", "Fallback reasons: " + ", ".join(f"{k} ({v})" for k, v in r.fallback_reasons.most_common())]
    return "\n".join(lines) + "\n"


def comparison_markdown(results: list[EvalResult]) -> str:
    """One table with a column per run, for rules-versus-AI comparisons."""
    head = "| | " + " | ".join(r.label for r in results) + " |"
    sep = "|---" * (len(results) + 1) + "|"

    def row(name, fn):
        return f"| {name} | " + " | ".join(fn(r) for r in results) + " |"

    lines = [
        head, sep,
        row("Breaks detected", lambda r: f"{r.detected}/{r.planted} ({r.detection_rate:.1%})"),
        row("Correct cause (of detected)", lambda r: f"{r.correct}/{r.detected} ({r.classification_accuracy:.1%})"),
        row("False alarms", lambda r: f"{r.false_alarms}/{r.cases} ({r.false_alarm_rate:.1%})"),
    ]
    for cat in PLANTABLE:
        lines.append(row(f"Correct: {cat.value}",
                         lambda r, c=cat: f"{r.per_category[c]['correct']}/{r.per_category[c]['planted']}"))
    lines += [
        row("AI responses accepted", lambda r: f"{r.ai_accepted}/{r.ai_calls}" if r.ai_calls else "n/a"),
        row("Fell back to rules", lambda r: str(r.ai_fallbacks) if r.ai_calls else "n/a"),
        row("Disagreed with rules (AI right / rules right)",
            lambda r: f"{r.disagreements} ({r.disagreements_ai_right} / {r.disagreements_rules_right})"
            if r.ai_calls else "n/a"),
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- multi-day


@dataclass
class SequenceEvalResult:
    days: int
    label: str = "Rules only"
    planted: int = 0
    detected_first_day: int = 0
    correct_first_day: int = 0
    due_to_clear: int = 0  # planted breaks whose fix day falls inside the window
    cleared_on_fix_day: int = 0
    cleared_early: int = 0
    not_cleared: int = 0
    correct_at_resolution: int = 0
    resolved_matched: int = 0
    false_alarm_cases: int = 0
    total_cases: int = 0
    escalated_open: int = 0
    sla_breached_open: int = 0
    days_to_resolve: list[int] = field(default_factory=list)
    open_at_end: Counter = field(default_factory=Counter)  # age bucket -> count
    per_category: dict[Category, Counter] = field(default_factory=dict)

    @property
    def avg_days_to_resolve(self) -> float:
        return sum(self.days_to_resolve) / len(self.days_to_resolve) if self.days_to_resolve else 0.0


def run_sequence_evaluation(
    days: int = 20,
    breaks_per_day: int = 10,
    seed: int = 42,
    difficulty: str = "standard",
    start: date = date(2026, 10, 1),
    ai_client: LLMClient | None = None,
    ai_cache: ResponseCache | None = None,
    audit: AuditLog | None = None,
    max_workers: int = 8,
) -> SequenceEvalResult:
    """Run consecutive days through the full pipeline and score the lifecycle.

    For each planted break: was a case raised the day it appeared, was the
    first-day cause right, did the case clear automatically on the day the data
    was fixed (not before, not after), and was the cause right at resolution?
    """
    from reconpilot.ledger import LifecycleSettings, days_to_resolve
    from reconpilot.matching import carry_forward
    from reconpilot.pipeline import run_day
    from reconpilot.sequence import SequenceConfig, generate_sequence

    seq = generate_sequence(start, days, breaks_per_day, seed, SequenceConfig(difficulty=difficulty))
    label = f"AI ({ai_client.model})" if ai_client else "Rules only"
    r = SequenceEvalResult(days=days, label=label, per_category={c: Counter() for c in PLANTABLE})
    settings = LifecycleSettings()
    planted: dict[tuple[str, date], PlantedBreak] = {}
    for _, truth in seq:
        for p in truth:
            planted.setdefault((p.security_id, p.start), p)

    prior_open: list[Case] = []
    prev = None
    seen_case_ids: set[str] = set()
    for day, truth in seq:
        if prev is not None:
            day.carried_book_items, day.carried_custodian_lines = carry_forward(prev.recon)
        res = run_day(day, prior_open, settings, use_ai=ai_client is not None, ai_client=ai_client,
                      ai_cache=ai_cache, audit=audit, actor="evaluate", max_workers=max_workers)
        prev, prior_open = res, res.open_cases
        live = {p.security_id: p for p in truth}
        by_sid = {c.security_id: c for c in res.open_cases}

        for c in res.open_cases:
            if c.case_id not in seen_case_ids:
                seen_case_ids.add(c.case_id)
                r.total_cases += 1
                if c.security_id not in live:
                    r.false_alarm_cases += 1

        for p in truth:
            if p.start != day.as_of:
                continue
            stats = r.per_category[p.category]
            stats["planted"] += 1
            r.planted += 1
            case = by_sid.get(p.security_id)
            if case is not None:
                stats["detected"] += 1
                r.detected_first_day += 1
                if scored_category(case) is p.category:
                    stats["correct_first_day"] += 1
                    r.correct_first_day += 1

        for c in res.cleared:
            p = next((p for (sid, started), p in planted.items()
                      if sid == c.security_id and str(started) == c.first_seen), None)
            if p is None:
                continue
            r.resolved_matched += 1
            if p.fix > day.as_of:
                r.cleared_early += 1
            if c.resolved_category is p.category:
                r.correct_at_resolution += 1
                r.per_category[p.category]["correct_at_resolution"] += 1
            d = days_to_resolve(c)
            if d is not None:
                r.days_to_resolve.append(d)

        cleared_today = {c.security_id for c in res.cleared}
        for (sid, started), p in planted.items():
            if p.fix == day.as_of:
                r.due_to_clear += 1
                r.per_category[p.category]["due_to_clear"] += 1
                if sid in cleared_today:
                    r.cleared_on_fix_day += 1
                    r.per_category[p.category]["cleared_on_fix_day"] += 1
                else:
                    r.not_cleared += 1

    r.escalated_open = sum(1 for c in prior_open if c.escalated)
    r.sla_breached_open = sum(1 for c in prior_open if c.sla_breached)
    for c in prior_open:
        r.open_at_end[c.age_bucket] += 1
    return r


def sequence_markdown(results: list[SequenceEvalResult], title: str) -> str:
    def row(name, fn):
        return f"| {name} | " + " | ".join(fn(r) for r in results) + " |"

    def pct(a, b):
        return f"{a}/{b} ({a / b:.1%})" if b else "n/a"

    first = results[0]
    lines = [
        f"## {title}",
        "",
        f"{first.days} consecutive business days, {first.planted} breaks planted, each fixed 1 to 6 business "
        "days later (late settlements 1 to 2 days).",
        "",
        "| | " + " | ".join(r.label for r in results) + " |",
        "|---" * (len(results) + 1) + "|",
        row("Detected on the day they appeared", lambda r: pct(r.detected_first_day, r.planted)),
        row("Cause right on the first day (of detected)", lambda r: pct(r.correct_first_day, r.detected_first_day)),
        row("Cleared automatically on the fix day", lambda r: pct(r.cleared_on_fix_day, r.due_to_clear)),
        row("Cleared before the data was fixed", lambda r: str(r.cleared_early)),
        row("Cause right at resolution (of cleared)", lambda r: pct(r.correct_at_resolution, r.resolved_matched)),
        row("Cases with no planted break (false alarms)", lambda r: pct(r.false_alarm_cases, r.total_cases)),
        row("Average business days to resolve", lambda r: f"{r.avg_days_to_resolve:.2f}"),
        row("Open at the end (0-1 / 2-5 / >5 days)",
            lambda r: " / ".join(str(r.open_at_end.get(b, 0)) for b in ("0-1", "2-5", ">5"))),
        row("Open at the end: escalated / SLA breached",
            lambda r: f"{r.escalated_open} / {r.sla_breached_open}"),
        "",
        "| Planted cause | " + " | ".join(
            f"{r.label}: right on day one / cleared on fix day / right at resolution" for r in results) + " |",
        "|---" * (len(results) + 1) + "|",
    ]
    for cat in PLANTABLE:
        cells = []
        for r in results:
            s = r.per_category[cat]
            cells.append(f"{s['correct_first_day']}/{s['planted']} / {s['cleared_on_fix_day']}/{s['due_to_clear']}"
                         f" / {s['correct_at_resolution']}/{s['cleared_on_fix_day']}")
        lines.append(f"| {cat.value} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
