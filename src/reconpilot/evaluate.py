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
from reconpilot.models import PLANTABLE, Case, Category
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
