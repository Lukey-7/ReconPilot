"""Score the pipeline against breaks planted by the generator.

For each planted break we ask two questions: did a case get raised on that
security (detection), and was the suggested cause right (classification)?
Cases raised on securities where nothing was planted are false alarms.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from reconpilot.generator import GeneratorConfig, generate_day
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE, Category
from reconpilot.triage import triage


@dataclass
class EvalResult:
    days: int
    planted: int = 0
    detected: int = 0
    correct: int = 0
    cases: int = 0
    false_alarms: int = 0
    per_category: dict[Category, Counter] = field(default_factory=dict)
    confusion: Counter = field(default_factory=Counter)  # (planted, suggested) -> count

    @property
    def detection_rate(self) -> float:
        return self.detected / self.planted if self.planted else 0.0

    @property
    def classification_accuracy(self) -> float:
        return self.correct / self.detected if self.detected else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / self.cases if self.cases else 0.0


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
) -> EvalResult:
    rng = random.Random(seed)
    schedule = [PLANTABLE[i % len(PLANTABLE)] for i in range(days * breaks_per_day)]
    rng.shuffle(schedule)
    result = EvalResult(days=days, per_category={c: Counter() for c in PLANTABLE})
    config = GeneratorConfig(difficulty=difficulty)

    for i, as_of in enumerate(business_days(start, days)):
        plants = schedule[i * breaks_per_day:(i + 1) * breaks_per_day]
        day, truth = generate_day(as_of, plants, seed=rng.randrange(2**31), config=config)
        cases = triage(day, reconcile(day))
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
            result.confusion[(p.category, case.category)] += 1
            if case.category is p.category:
                stats["correct"] += 1
                result.correct += 1
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
    return "\n".join(lines) + "\n"
