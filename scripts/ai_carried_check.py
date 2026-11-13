"""Acceptance check for the AI on carried cases (design spec, section 9).

Runs the 8-day hard sequence (seed 21, 6 new breaks a day) through the full
pipeline with the configured AI provider, exactly as ``reconpilot evaluate
--multi-day --hard --ai`` does, and measures, on every day:

* **new cases**: open cases on the day they first appear;
* **carried cases**: open cases on day two of their life onwards;

each matched to the planted break live on its security that day. For both it
counts how often the rules and the AI named the planted cause (the AI's answer
is the one that passed the guardrails, else the rules' fallback, as the
evaluator scores it). It also counts **unflagged disagreements**: open cases
whose accepted AI answer differs from the rules' cause without the "AI
disagrees: needs review" flag.

Acceptance: the AI is at least as accurate on carried cases as on new ones, and
no disagreement goes unflagged. The exit status is 0 when both hold, 1 otherwise.

    source keys.env   # sets OPENAI_API_KEY (never commit keys)
    python scripts/ai_carried_check.py --provider openai

Responses are cached by prompt hash (``--cache``), so a second run costs nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date

from reconpilot.ai import DEFAULT_MODELS, ResponseCache, make_client
from reconpilot.audit import AuditLog
from reconpilot.evaluate import scored_category
from reconpilot.ledger import LifecycleSettings
from reconpilot.matching import carry_forward
from reconpilot.pipeline import run_day
from reconpilot.sequence import SequenceConfig, generate_sequence

START = date(2026, 10, 1)  # the evaluator's default start


def measure(client, cache, days: int, breaks: int, seed: int, audit: AuditLog | None, verbose: bool) -> dict:
    seq = generate_sequence(START, days, breaks, seed, SequenceConfig(difficulty="hard"))
    stats = {kind: Counter() for kind in ("new", "carried")}
    unflagged: list[tuple[str, str, str, str]] = []
    flagged = 0
    misses: list[str] = []
    prior_open, prev = [], None
    for day, truth in seq:
        if prev is not None:
            day.carried_book_items, day.carried_custodian_lines = carry_forward(prev.recon, prev.day)
        res = run_day(day, prior_open, LifecycleSettings(), use_ai=True, ai_client=client, ai_cache=cache,
                      audit=audit, actor="ai-carried-check")
        prev, prior_open = res, res.open_cases
        live = {p.security_id: p for p in truth}

        for c in res.open_cases:
            if c.ai_status == "ACCEPTED" and c.ai_category is not c.category:
                if c.ai_flag:
                    flagged += 1
                else:
                    unflagged.append((str(day.as_of), c.case_id, c.category.value, c.ai_category.value))
            p = live.get(c.security_id)
            if p is None:
                continue
            kind = "new" if c.first_seen == str(day.as_of) else "carried"
            s = stats[kind]
            s["cases"] += 1
            s["rules_right"] += c.category is p.category
            s["ai_right"] += scored_category(c) is p.category
            s["ai_accepted"] += c.ai_status == "ACCEPTED"
            if scored_category(c) is not p.category:
                misses.append(f"{day.as_of} {kind:<7} {c.case_id} {c.security_id or '(none)':<14} planted "
                              f"{p.category.value:<14} rules {c.category.value:<14} AI "
                              f"{c.ai_category.value if c.ai_category else 'fallback: ' + c.ai_fallback_reason[:50]}")
    if verbose and misses:
        print("Cases where the AI's answer was not the planted cause:")
        for line in misses:
            print("  " + line)
        print()
    return {"stats": stats, "unflagged": unflagged, "flagged": flagged}


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.1%})" if b else "n/a"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--provider", choices=sorted(DEFAULT_MODELS),
                   help="default: the first of anthropic, openai, google with a key set")
    p.add_argument("--model", help="default depends on the provider (openai: gpt-6-luna)")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--cache", default=".reconpilot_cache/ai", help="folder for cached responses")
    p.add_argument("--days", type=int, default=8)
    p.add_argument("--breaks", type=int, default=6)
    p.add_argument("--seed", type=int, default=21)
    p.add_argument("--audit", help="write every AI call to this audit log (JSON lines)")
    p.add_argument("-v", "--verbose", action="store_true", help="list every case the AI got wrong")
    a = p.parse_args(argv)

    client = make_client(a.provider, a.model, a.effort, a.timeout)
    if client is None:
        print("No API key found: set OPENAI_API_KEY (or ANTHROPIC_API_KEY / GOOGLE_API_KEY).", file=sys.stderr)
        return 2
    print(f"AI: {client.provider} / {client.model} (effort {client.effort}); "
          f"{a.days}-day hard run, seed {a.seed}, {a.breaks} new breaks a day\n")
    r = measure(client, ResponseCache(a.cache), a.days, a.breaks, a.seed,
                AuditLog(a.audit) if a.audit else None, a.verbose)

    new, carried = r["stats"]["new"], r["stats"]["carried"]
    print("| | Rules right | AI right | AI accepted by the guardrails |")
    print("|---|---|---|---|")
    for label, s in (("New cases (first day)", new), ("Carried cases (day two onwards)", carried)):
        print(f"| {label} | {pct(s['rules_right'], s['cases'])} | {pct(s['ai_right'], s['cases'])} "
              f"| {s['ai_accepted']}/{s['cases']} |")
    print()
    print(f"Disagreements flagged: {r['flagged']}")
    print(f"Disagreements not flagged: {len(r['unflagged'])}")
    for as_of, case_id, rules, ai in r["unflagged"]:
        print(f"  {as_of} {case_id}: rules {rules}, AI {ai}")

    new_rate = new["ai_right"] / new["cases"] if new["cases"] else 0.0
    carried_rate = carried["ai_right"] / carried["cases"] if carried["cases"] else 0.0
    ok = carried["cases"] > 0 and carried_rate >= new_rate and not r["unflagged"]
    print()
    print(f"Acceptance (carried accuracy >= new accuracy, no unflagged disagreement): {'MET' if ok else 'NOT MET'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
