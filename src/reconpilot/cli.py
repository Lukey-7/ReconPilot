"""Command-line entry point.

    reconpilot generate --as-of 2026-11-13 --out data/2026-11-13
    reconpilot run      --data data/2026-11-13 --out runs/fund1 --user priya
    reconpilot queue    --run runs/fund1
    reconpilot review   --run runs/fund1 --user priya --case EX-20261113-001 --approve
    reconpilot signoff  --run runs/fund1 --user tom --role approver
    reconpilot verify-audit --run runs/fund1
    reconpilot evaluate --days 20 --breaks 10 --hard --ai
    reconpilot demo --ai
    reconpilot demo --days 5

A run directory holds one fund's history: run each business day into the same
``--out`` folder and open cases carry over, age, escalate and clear
automatically when later data matches. ``review`` and ``signoff`` act on the
most recent day run.

Add --ai to run, demo or evaluate for AI-assisted triage. The key comes from
ANTHROPIC_API_KEY, OPENAI_API_KEY or GOOGLE_API_KEY; without one, or without
the flag, everything runs on the rules alone.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

from reconpilot.ai import DEFAULT_MODELS, ResponseCache, make_client
from reconpilot.audit import AuditLog
from reconpilot.evaluate import (
    comparison_markdown,
    run_evaluation,
    run_sequence_evaluation,
    sequence_markdown,
    to_markdown,
)
from reconpilot.generator import GeneratorConfig, generate_day
from reconpilot.impact import DEFAULT_MATERIALITY_BP, release_check, sort_by_impact
from reconpilot.ledger import (
    LifecycleSettings,
    latest_before,
    load_ledger,
    load_open_items,
    save_ledger,
    save_open_items,
    snapshot_dates,
    update_ledger_cases,
)
from reconpilot.mi import write_mi_csv
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE, Category, DayData
from reconpilot.nav import compute_nav, run_checks
from reconpilot.pipeline import run_day
from reconpilot.report import write_report
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot.sequence import SequenceConfig, generate_sequence
from reconpilot.storage import load_cases, read_day, save_cases, write_day

ROLES = ["analyst", "approver", "viewer"]


def _plants(n: int, seed: int) -> list[Category]:
    rng = random.Random(seed)
    plants = [PLANTABLE[i % len(PLANTABLE)] for i in range(n)]
    rng.shuffle(plants)
    return plants


def cmd_generate(a) -> int:
    as_of = date.fromisoformat(a.as_of)
    if getattr(a, "days", 1) > 1:
        seq = generate_sequence(as_of, a.days, a.breaks, seed=a.seed,
                                config=SequenceConfig(difficulty="hard" if a.hard else "standard"))
        for day, truth in seq:
            write_day(day, Path(a.out) / str(day.as_of), truth)
        print(f"Wrote {len(seq)} business days ({seq[0][0].as_of} to {seq[-1][0].as_of}) to {a.out}, "
              f"one folder per day, with {a.breaks} new planted breaks a day")
        return 0
    day, truth = generate_day(as_of, _plants(a.breaks, a.seed), seed=a.seed,
                              config=GeneratorConfig(difficulty="hard" if a.hard else "standard"))
    out = write_day(day, a.out, truth)
    print(f"Wrote {as_of} data to {out} ({len(day.book_trades)} trades, {len(day.custodian_cash)} cash lines, "
          f"{len(truth)} planted breaks in planted_breaks.json)")
    return 0


def _ai_setup(a):
    """Return (client, cache) for --ai, or (None, None). Warn when no key is set."""
    if not getattr(a, "ai", False):
        return None, None
    client = make_client(a.ai_provider, a.ai_model, a.ai_effort, a.ai_timeout)
    if client is None:
        print("--ai given but no API key found; continuing with rule-based triage only.", file=sys.stderr)
        return None, None
    print(f"AI triage: {client.provider} / {client.model} (effort {client.effort})")
    return client, ResponseCache(a.ai_cache)


# --------------------------------------------------------------------------- run directory state


def _state_path(run: Path) -> Path:
    return run / "run.json"


def _load_state(run: Path) -> dict:
    state = json.loads(_state_path(run).read_text(encoding="utf-8"))
    state.setdefault("days", {})
    if not state["days"] and "data_dir" in state:  # run directories from before multi-day support
        state["days"][state["as_of"]] = {"data_dir": state["data_dir"],
                                         "signed_off_by": state.get("signed_off_by", "")}
    return state


def _save_state(run: Path, state: dict) -> None:
    current = state["days"][state["as_of"]]
    state["data_dir"] = current["data_dir"]  # kept for older tools reading run.json
    state["signed_off_by"] = current.get("signed_off_by", "")
    _state_path(run).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _settings(state: dict) -> LifecycleSettings:
    return LifecycleSettings(**state.get("settings", {}))


def _load_day(run: Path, data_dir: str | Path) -> DayData:
    """Read a day's files and attach the open items carried from the previous run."""
    day = read_day(data_dir)
    prev = latest_before(run, day.as_of)
    if prev is not None:
        day.carried_book_items, day.carried_custodian_lines = load_open_items(run, prev)
    return day


def _render(run: Path, state: dict) -> Path:
    """Rebuild the report for the current day from saved data and saved cases."""
    as_of = state["as_of"]
    info = state["days"][as_of]
    day = _load_day(run, info["data_dir"])
    recon = reconcile(day)
    nav = compute_nav(day)
    checks = run_checks(day, nav, recon)
    cases = load_cases(run / "cases.json")
    settings = _settings(state)
    checks.append(release_check(cases, settings.materiality_bp))
    history = {str(d): load_ledger(run, d) for d in snapshot_dates(run) if str(d) <= as_of}
    write_mi_csv(run / "mi.csv", history)
    return write_report(run / f"exceptions_{day.as_of}.xlsx", day, recon, cases, nav, checks,
                        info.get("signed_off_by", ""), ledger=history[as_of], history=history)


def cmd_run(a) -> int:
    run = Path(a.out)
    run.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(run / "audit.jsonl")
    state = _load_state(run) if _state_path(run).exists() else {"days": {}}
    settings = LifecycleSettings(
        materiality_bp=a.materiality_bp,
        escalate_after_days=a.escalate_after,
        sla_days_material=a.sla_material,
        sla_days_other=a.sla_other,
    )
    state["settings"] = vars(settings)

    day = _load_day(run, a.data)
    prev = latest_before(run, day.as_of)
    history = load_ledger(run, prev) if prev else []
    prior_open = [c for c in history if not c.cleared_on]
    already_cleared = [c for c in history if c.cleared_on]
    audit.append(a.user, a.role, "RUN_STARTED", {
        "data_dir": str(Path(a.data).resolve()), "as_of": day.as_of, "previous_day": prev,
        "carried_cases": len(prior_open),
        "carried_cash_items": len(day.carried_book_items) + len(day.carried_custodian_lines),
    })

    client, cache = _ai_setup(a)
    result = run_day(day, prior_open, settings, use_ai=getattr(a, "ai", False), ai_client=client,
                     ai_cache=cache, audit=audit, actor=a.user, role=a.role)
    cases = result.open_cases
    save_cases(cases, run / "cases.json")
    save_ledger(run, day.as_of, already_cleared + result.cleared + cases)
    save_open_items(run, day.as_of, result.recon)
    audit.append(a.user, a.role, "CASES_RAISED", {
        "matches": len(result.recon.matches), "breaks": len(result.recon.breaks), "open_cases": len(cases),
        "cleared_today": [c.case_id for c in result.cleared],
        "nav_per_share": result.nav.nav_per_share,
        "material_cases": [c.case_id for c in cases if c.material],
        "checks": {c.name: c.status for c in result.checks},
    })
    state["as_of"] = str(day.as_of)
    state["days"][str(day.as_of)] = {"data_dir": str(Path(a.data).resolve()), "signed_off_by": ""}
    _save_state(run, state)
    report = _render(run, state)

    recon, nav = result.recon, result.nav
    print(f"{day.as_of}: {len(recon.matches)} cash matches, {len(recon.breaks)} breaks, "
          f"{len(cases)} open cases ({sum(1 for c in cases if c.first_seen == str(day.as_of))} new), "
          f"{len(result.cleared)} cleared automatically")
    for c in result.cleared:
        print(f"  cleared {c.case_id}  {c.security_id or '(none)':<14} {c.resolved_category.value:<15} "
              f"after {c.age_days} business day(s)")
    _print_queue(cases)
    print(f"NAV per share {nav.nav_per_share:,.6f} ({nav.movement:+.2%})")
    for c in result.checks:
        print(f"  [{c.status}] {c.name}")
    print(f"Report: {report}")
    return 0


def _print_queue(cases) -> None:
    print("Review queue, largest NAV impact first (M material, E escalated, S SLA breached):")
    for c in sort_by_impact(cases):
        flags = ("M" if c.material else " ") + ("E" if c.escalated else " ") + ("S" if c.sla_breached else " ")
        line = (f" {flags} {c.case_id}  {c.security_id or '(none)':<14} {c.nav_impact:>14,.2f} "
                f"{c.nav_impact_bp:>+7.2f}bp  age {c.age_days:>2}  {c.status:<12} "
                f"{c.category.value:<15} {c.confidence:.2f}")
        if c.ai_status == "ACCEPTED":
            line += f"   AI: {c.ai_category.value} {c.ai_confidence:.2f}"
            if c.ai_flag:
                line += f"  [{c.ai_flag}]"
        elif c.ai_status == "FALLBACK":
            line += f"   AI: fell back to rules ({c.ai_fallback_reason[:60]})"
        print(line)


def cmd_queue(a) -> int:
    run = Path(a.run)
    state = _load_state(run)
    print(f"Open cases for {state['as_of']}:")
    _print_queue(load_cases(run / "cases.json"))
    return 0


def cmd_review(a) -> int:
    run = Path(a.run)
    state = _load_state(run)
    cases = load_cases(run / "cases.json")
    session = ReviewSession(cases, AuditLog(run / "audit.jsonl"), a.user, a.role)
    decisions = []
    if a.decisions:
        with open(a.decisions, newline="", encoding="utf-8") as fh:
            decisions = [(r["case_id"], r["decision"].lower(), r.get("category", ""), r.get("note", ""))
                         for r in csv.DictReader(fh)]
    elif a.case:
        decision = "approve" if a.approve else "reject" if a.reject else "reclassify"
        decisions = [(a.case, decision, a.reclassify or "", a.note or "")]
    else:
        print("Give --case with --approve/--reject/--reclassify, or --decisions FILE", file=sys.stderr)
        return 2
    try:
        for case_id, decision, category, note in decisions:
            if decision == "approve":
                session.approve(case_id, note)
            elif decision == "reject":
                session.reject(case_id, note)
            elif decision == "reclassify":
                session.reclassify(case_id, category.upper(), note)
            else:
                raise ReviewError(f"unknown decision {decision!r}")
            print(f"{case_id}: {decision}")
    except (PermissionDenied, ReviewError, ValueError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    finally:
        changed = list(session.cases.values())
        save_cases(changed, run / "cases.json")
        update_ledger_cases(run, state["as_of"], changed)
        _render(run, state)
    print(f"{len(session.pending())} case(s) still pending")
    return 0


def cmd_signoff(a) -> int:
    run = Path(a.run)
    state = _load_state(run)
    session = ReviewSession(load_cases(run / "cases.json"), AuditLog(run / "audit.jsonl"), a.user, a.role)
    try:
        session.sign_off()
    except (PermissionDenied, ReviewError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    state["days"][state["as_of"]]["signed_off_by"] = a.user
    _save_state(run, state)
    print(f"Signed off by {a.user}. Report: {_render(run, state)}")
    return 0


def cmd_verify(a) -> int:
    ok, bad = AuditLog(Path(a.run) / "audit.jsonl").verify()
    print("Audit chain intact." if ok else f"Audit chain broken at entry {bad}.")
    return 0 if ok else 1


def cmd_evaluate(a) -> int:
    difficulty = "hard" if a.hard else "standard"
    if a.multi_day:
        results = [run_sequence_evaluation(days=a.days, breaks_per_day=a.breaks, seed=a.seed,
                                           difficulty=difficulty)]
        client, cache = _ai_setup(a)
        if client is not None:
            audit = AuditLog(Path(a.ai_cache).parent / "evaluate_audit.jsonl")
            results.append(run_sequence_evaluation(days=a.days, breaks_per_day=a.breaks, seed=a.seed,
                                                   difficulty=difficulty, ai_client=client, ai_cache=cache,
                                                   audit=audit))
        text = sequence_markdown(results, f"Multi-day ({difficulty} data, seed {a.seed})")
        print(text)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        return 0
    base = run_evaluation(days=a.days, breaks_per_day=a.breaks, seed=a.seed, difficulty=difficulty)
    text = to_markdown(base, f"Rules only ({difficulty} data, seed {a.seed})")
    client, cache = _ai_setup(a)
    if client is not None:
        audit = AuditLog(Path(a.ai_cache).parent / "evaluate_audit.jsonl")
        ai = run_evaluation(days=a.days, breaks_per_day=a.breaks, seed=a.seed, difficulty=difficulty,
                            ai_client=client, ai_cache=cache, audit=audit)
        heading = f"## Rules versus AI ({difficulty} data, seed {a.seed})"
        ai_text = to_markdown(ai, f"{ai.label} ({difficulty} data, seed {a.seed})")
        text = "\n\n".join([heading, comparison_markdown([base, ai]), text, ai_text])
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


def cmd_demo(a) -> int:
    root = Path(a.dir)
    ai = {k: getattr(a, k) for k in _AI_ARGS}
    if a.days > 1:
        start = "2026-11-09"
        cmd_generate(argparse.Namespace(as_of=start, out=root / "data", seed=7, breaks=4, hard=a.hard, days=a.days))
        for folder in sorted((root / "data").iterdir()):
            print()
            rc = cmd_run(_run_args(data=folder, out=root / "run", user="analyst1", role="analyst", **ai))
            if rc:
                return rc
        return 0
    cmd_generate(argparse.Namespace(as_of="2026-11-13", out=root / "data", seed=7, breaks=12, hard=a.hard, days=1))
    return cmd_run(_run_args(data=root / "data", out=root / "run", user="analyst1", role="analyst", **ai))


_AI_ARGS = ("ai", "ai_provider", "ai_model", "ai_effort", "ai_timeout", "ai_cache")


def _run_args(**overrides) -> argparse.Namespace:
    """Defaults for ``run`` when called from other commands."""
    defaults = LifecycleSettings()
    base = dict(materiality_bp=defaults.materiality_bp, escalate_after=defaults.escalate_after_days,
                sla_material=defaults.sla_days_material, sla_other=defaults.sla_days_other,
                ai=False, ai_provider=None, ai_model=None, ai_effort="medium", ai_timeout=120.0,
                ai_cache=".reconpilot_cache/ai")
    base.update(overrides)
    return argparse.Namespace(**base)


def _add_ai_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("AI-assisted triage")
    g.add_argument("--ai", action="store_true", help="add an AI second opinion to every case")
    g.add_argument("--ai-provider", choices=sorted(DEFAULT_MODELS),
                   help="default: the first of anthropic, openai, google with a key set")
    g.add_argument("--ai-model", help="model name; default depends on the provider")
    g.add_argument("--ai-effort", default="medium", choices=["low", "medium", "high"],
                   help="reasoning effort, where the provider supports it")
    g.add_argument("--ai-timeout", type=float, default=120.0, help="seconds per call")
    g.add_argument("--ai-cache", default=".reconpilot_cache/ai", help="folder for cached responses")


def _add_lifecycle_args(p: argparse.ArgumentParser) -> None:
    d = LifecycleSettings()
    g = p.add_argument_group("materiality, escalation and SLAs")
    g.add_argument("--materiality-bp", type=float, default=d.materiality_bp,
                   help="cases at or above this NAV impact (basis points) are material")
    g.add_argument("--escalate-after", type=int, default=d.escalate_after_days,
                   help="escalate cases open longer than this many business days")
    g.add_argument("--sla-material", type=int, default=d.sla_days_material,
                   help="business days to resolve a material case")
    g.add_argument("--sla-other", type=int, default=d.sla_days_other,
                   help="business days to resolve any other case")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reconpilot", description="Daily fund reconciliation and NAV checks.")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write a synthetic day with planted breaks")
    g.add_argument("--as-of", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--breaks", type=int, default=12)
    g.add_argument("--hard", action="store_true", help="noisier data that is harder to classify")
    g.add_argument("--days", type=int, default=1,
                   help="generate this many consecutive business days, one folder each, with breaks "
                        "that persist until fixed (--breaks is then new breaks per day)")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("run", help="reconcile a day, roll cases forward, check NAV and write the report")
    r.add_argument("--data", required=True)
    r.add_argument("--out", required=True, help="run directory; reuse it every day for one fund")
    r.add_argument("--user", required=True)
    r.add_argument("--role", choices=ROLES, default="analyst")
    _add_lifecycle_args(r)
    _add_ai_args(r)
    r.set_defaults(func=cmd_run)

    q = sub.add_parser("queue", help="show open cases, largest NAV impact first")
    q.add_argument("--run", required=True)
    q.set_defaults(func=cmd_queue)

    v = sub.add_parser("review", help="approve, reject or reclassify cases")
    v.add_argument("--run", required=True)
    v.add_argument("--user", required=True)
    v.add_argument("--role", choices=ROLES, default="analyst")
    v.add_argument("--case")
    act = v.add_mutually_exclusive_group()
    act.add_argument("--approve", action="store_true")
    act.add_argument("--reject", action="store_true")
    act.add_argument("--reclassify", choices=[c.value for c in Category])
    v.add_argument("--note")
    v.add_argument("--decisions", help="CSV with case_id, decision, category, note")
    v.set_defaults(func=cmd_review)

    s = sub.add_parser("signoff", help="release the NAV for the day (approver, four-eyes)")
    s.add_argument("--run", required=True)
    s.add_argument("--user", required=True)
    s.add_argument("--role", choices=ROLES, default="approver")
    s.set_defaults(func=cmd_signoff)

    a = sub.add_parser("verify-audit", help="check the audit log hash chain")
    a.add_argument("--run", required=True)
    a.set_defaults(func=cmd_verify)

    e = sub.add_parser("evaluate", help="score detection and classification on planted breaks")
    e.add_argument("--days", type=int, default=20)
    e.add_argument("--breaks", type=int, default=10)
    e.add_argument("--seed", type=int, default=42)
    e.add_argument("--hard", action="store_true")
    e.add_argument("--multi-day", action="store_true",
                   help="score ageing and auto-clearing over consecutive days instead of independent days")
    e.add_argument("--out")
    _add_ai_args(e)
    e.set_defaults(func=cmd_evaluate)

    d = sub.add_parser("demo", help="generate a sample day and run it end to end")
    d.add_argument("--dir", default="demo")
    d.add_argument("--hard", action="store_true", help="generate the noisier data")
    d.add_argument("--days", type=int, default=1, help="run this many consecutive business days")
    _add_ai_args(d)
    d.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
