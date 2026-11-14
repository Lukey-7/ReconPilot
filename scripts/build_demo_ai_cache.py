"""Build the demo's AI cache (design spec, section 11) by running the real AI on the demo's seed.

The public demo answers every AI question from a cache, so it needs no API key and costs
nothing to run. This script fills that cache: on a throwaway embedded PostgreSQL in demo
mode it builds a visitor fund exactly as "Try the demo" does, then works and signs off
every day and generates the next, to the end of the demo's sequence
(``demo.DEMO_HORIZON`` business days), with the configured provider standing in for the
cache-only client. Every case of every day is therefore asked of the real AI through the
web application's own code, so the prompts and their hashes are exactly those a visitor's
fund will ask. A second pass asks again only what the first could not answer (a timeout,
say); a final pass with the cache-only client counts any question left unanswered.

The responses (and nothing else: no key, no prompt) are written to
``src/reconpilot_web/demo_ai_cache.json``, which a demo instance loads into its database
when it starts.

    source keys.env   # sets OPENAI_API_KEY (never commit keys)
    python scripts/build_demo_ai_cache.py --provider openai
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_fund(factory, label: str) -> str:
    """A demo fund worked from the first day to the last of the sequence; its code."""
    from reconpilot_web import demo
    from reconpilot_web.release import sign_off_day

    days = demo.demo_days()
    with factory() as session, session.begin():
        fund, team = demo.create_demo_fund(session, label, max_funds=1000, per_hour=1000)
        print(f"  {fund.code}: the first {demo.DEMO_WEEK} days built", flush=True)
        for previous, day in zip(days[demo.DEMO_WEEK - 1:], days[demo.DEMO_WEEK:]):
            demo.review_day(session, fund, previous, team)
            sign_off_day(session, fund, previous.as_of, team[demo.SIGNER])
            demo.load_demo_day(session, fund, day, team[demo.ANALYST])
            demo.run_inline(session, fund, day.as_of, team[demo.ANALYST])
            print(f"  {fund.code}: {day.as_of} run", flush=True)
        return fund.code


def ai_calls(factory, code: str) -> list[dict]:
    from sqlalchemy import select

    from reconpilot_web.models import AuditEntry, Fund

    with factory() as session:
        fund_id = session.execute(select(Fund.id).where(Fund.code == code)).scalar_one()
        return list(session.execute(
            select(AuditEntry.payload)
            .where(AuditEntry.fund_id == fund_id, AuditEntry.action == "AI_CALL")
            .order_by(AuditEntry.seq)
        ).scalars())


def main(argv: list[str] | None = None) -> int:
    from reconpilot.ai import PROMPT_VERSION, make_client
    from reconpilot_web import aicache, cli, db, demo, devdb, runner
    from reconpilot_web.config import load_settings
    from reconpilot_web.models import AICacheEntry

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", default="openai", choices=("openai", "anthropic", "google"))
    parser.add_argument("--model", default=None, help="the provider's model (default: the engine's)")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=aicache.DEMO_CACHE_FILE)
    args = parser.parse_args(argv)

    client = make_client(args.provider, args.model, args.effort, args.timeout)
    if client is None:
        print(f"No API key for {args.provider}: set its key in the environment first.", file=sys.stderr)
        return 1

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    data_dir = Path(tempfile.mkdtemp(prefix="reconpilot_demo_cache_"))
    try:
        uri = devdb.start(data_dir)
        settings = load_settings({"RP_DATABASE_URL": uri, "RP_MODE": "demo", "RP_DATA_DIR": str(data_dir)})
        cli.migrate(settings)
        engine = db.make_engine(uri)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        print(f"Asking {client.provider} {client.model} (effort {client.effort}) about every case of the demo's "
              f"{demo.DEMO_HORIZON} days (seed {demo.DEMO_SEED}).", flush=True)
        runner.demo_ai_client = lambda: client
        for n in (1, 2):
            print(f"Pass {n}:", flush=True)
            code = build_fund(factory, f"cache-build-{n}")
            calls = ai_calls(factory, code)
            fresh = sum(1 for c in calls if not c["cached"])
            print(f"  {len(calls)} questions, {fresh} asked of the provider this pass", flush=True)

        with factory() as session:
            rows = session.execute(
                select(AICacheEntry.key, AICacheEntry.response)
                .where(AICacheEntry.provider == client.provider, AICacheEntry.model == client.model)
                .order_by(AICacheEntry.key)
            ).all()
        cache = {
            "about": "The ReconPilot demo's AI answers, built by scripts/build_demo_ai_cache.py with the real AI "
                     "for the demo's fixed seed. Responses only, keyed by the engine's prompt hash.",
            "seed": demo.DEMO_SEED,
            "breaks_per_day": demo.DEMO_BREAKS_PER_DAY,
            "difficulty": "hard",
            "start": str(demo.DEMO_START),
            "days": demo.DEMO_HORIZON,
            "provider": client.provider,
            "model": client.model,
            "effort": client.effort,
            "prompt_version": PROMPT_VERSION,
            "built_at": datetime.now(timezone.utc).date().isoformat(),
            "responses": {key: response for key, response in rows},
        }
        args.out.write_text(json.dumps(cache, indent=1, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(rows)} responses to {args.out}.", flush=True)

        # Check: a fund built with the cache-only client, as a visitor's is, finds every answer.
        runner.demo_ai_client = lambda: aicache.CacheOnlyClient(client.provider, client.model, client.effort)
        print("Check with the cache-only client:", flush=True)
        code = build_fund(factory, "cache-check")
        calls = ai_calls(factory, code)
        missing = [c for c in calls if c.get("fallback_reason") == aicache.CACHE_MISS]
        outcomes = Counter("disagrees" if c["disagrees"] else "fallback" if c["fallback_used"] else "agrees"
                           for c in calls)
        print(f"  {len(calls)} questions: {len(missing)} not in the cache; answers {dict(outcomes)}")
        for c in calls:
            if c["fallback_used"] and c.get("fallback_reason") != aicache.CACHE_MISS:
                print(f"  {c['case_id']}: guardrail fallback: {c['fallback_reason']}")
        engine.dispose()
        return 0 if not missing else 1
    finally:
        devdb.stop(data_dir)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
