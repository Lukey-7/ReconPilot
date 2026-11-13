"""Command-line entry point.

    reconpilot generate --as-of 2026-11-13 --out data/2026-11-13
    reconpilot run      --data data/2026-11-13 --out runs/2026-11-13 --user priya
    reconpilot review   --run runs/2026-11-13 --user priya --case EX-20261113-001 --approve
    reconpilot signoff  --run runs/2026-11-13 --user tom --role approver
    reconpilot verify-audit --run runs/2026-11-13
    reconpilot evaluate --days 20 --breaks 10
    reconpilot demo
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

from reconpilot.audit import AuditLog
from reconpilot.evaluate import run_evaluation, to_markdown
from reconpilot.generator import GeneratorConfig, generate_day
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE, Category
from reconpilot.nav import compute_nav, run_checks
from reconpilot.report import write_report
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot.storage import load_cases, read_day, save_cases, write_day
from reconpilot.triage import triage

ROLES = ["analyst", "approver", "viewer"]


def _plants(n: int, seed: int) -> list[Category]:
    rng = random.Random(seed)
    plants = [PLANTABLE[i % len(PLANTABLE)] for i in range(n)]
    rng.shuffle(plants)
    return plants


def cmd_generate(a) -> int:
    as_of = date.fromisoformat(a.as_of)
    day, truth = generate_day(as_of, _plants(a.breaks, a.seed), seed=a.seed,
                              config=GeneratorConfig(difficulty="hard" if a.hard else "standard"))
    out = write_day(day, a.out, truth)
    print(f"Wrote {as_of} data to {out} ({len(day.book_trades)} trades, {len(day.custodian_cash)} cash lines, "
          f"{len(truth)} planted breaks in planted_breaks.json)")
    return 0


def _state_path(run: Path) -> Path:
    return run / "run.json"


def _load_state(run: Path) -> dict:
    return json.loads(_state_path(run).read_text(encoding="utf-8"))


def _render(run: Path, state: dict) -> Path:
    day = read_day(state["data_dir"])
    recon = reconcile(day)
    nav = compute_nav(day)
    checks = run_checks(day, nav, recon)
    cases = load_cases(run / "cases.json")
    return write_report(run / f"exceptions_{day.as_of}.xlsx", day, recon, cases, nav, checks,
                        state.get("signed_off_by", ""))


def cmd_run(a) -> int:
    run = Path(a.out)
    run.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(run / "audit.jsonl")
    day = read_day(a.data)
    audit.append(a.user, a.role, "RUN_STARTED", {"data_dir": str(Path(a.data).resolve()), "as_of": day.as_of})
    recon = reconcile(day)
    cases = triage(day, recon)
    nav = compute_nav(day)
    checks = run_checks(day, nav, recon)
    save_cases(cases, run / "cases.json")
    audit.append(a.user, a.role, "CASES_RAISED", {
        "matches": len(recon.matches), "breaks": len(recon.breaks), "cases": len(cases),
        "nav_per_share": nav.nav_per_share,
        "checks": {c.name: c.status for c in checks},
    })
    state = {"data_dir": str(Path(a.data).resolve()), "as_of": str(day.as_of)}
    _state_path(run).write_text(json.dumps(state, indent=2), encoding="utf-8")
    report = _render(run, state)

    print(f"{day.as_of}: {len(recon.matches)} cash matches, {len(recon.breaks)} breaks, {len(cases)} cases")
    for c in cases:
        print(f"  {c.case_id}  {c.security_id:<14} {c.category.value:<15} {c.confidence:.2f}")
    print(f"NAV per share {nav.nav_per_share:,.6f} ({nav.movement:+.2%})")
    for c in checks:
        print(f"  [{c.status}] {c.name}")
    print(f"Report: {report}")
    return 0


def cmd_review(a) -> int:
    run = Path(a.run)
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
        save_cases(list(session.cases.values()), run / "cases.json")
        _render(run, _load_state(run))
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
    state["signed_off_by"] = a.user
    _state_path(run).write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Signed off by {a.user}. Report: {_render(run, state)}")
    return 0


def cmd_verify(a) -> int:
    ok, bad = AuditLog(Path(a.run) / "audit.jsonl").verify()
    print("Audit chain intact." if ok else f"Audit chain broken at entry {bad}.")
    return 0 if ok else 1


def cmd_evaluate(a) -> int:
    difficulty = "hard" if a.hard else "standard"
    result = run_evaluation(days=a.days, breaks_per_day=a.breaks, seed=a.seed, difficulty=difficulty)
    text = to_markdown(result, f"Evaluation ({difficulty} data, seed {a.seed})")
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


def cmd_demo(a) -> int:
    root = Path(a.dir)
    as_of = "2026-11-13"
    cmd_generate(argparse.Namespace(as_of=as_of, out=root / "data", seed=7, breaks=12, hard=False))
    return cmd_run(argparse.Namespace(data=root / "data", out=root / "run", user="analyst1", role="analyst"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reconpilot", description="Daily fund reconciliation and NAV checks.")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write a synthetic day with planted breaks")
    g.add_argument("--as-of", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--breaks", type=int, default=12)
    g.add_argument("--hard", action="store_true", help="noisier data that is harder to classify")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("run", help="reconcile a day, raise cases, check NAV and write the report")
    r.add_argument("--data", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--user", required=True)
    r.add_argument("--role", choices=ROLES, default="analyst")
    r.set_defaults(func=cmd_run)

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

    s = sub.add_parser("signoff", help="close the day (approver, four-eyes)")
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
    e.add_argument("--out")
    e.set_defaults(func=cmd_evaluate)

    d = sub.add_parser("demo", help="generate a sample day and run it end to end")
    d.add_argument("--dir", default="demo")
    d.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
