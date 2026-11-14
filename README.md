# ReconPilot

AI-assisted break triage and investigation for fund reconciliation, sitting on
top of a deterministic, auditable matching engine.

Every business day a fund administrator compares three records: the fund's own
trades and positions, the custodian's holdings statement, and the custodian's
cash statement. Anything that does not agree is a break. Breaks have to be
found, explained, chased with the custodian and signed off before the NAV goes
out. ReconPilot runs that loop end to end. A rules engine finds the breaks;
a language model reads the evidence for each one and suggests the cause, explains
it with the actual figures, lists the investigation steps and drafts the query
to the custodian. An analyst approves every suggestion before anything happens.

## Who does what

| Step | Done by | Why |
|---|---|---|
| Match positions and cash, apply tolerances | Deterministic engine | Must be exact, repeatable and explainable to an auditor |
| Calculate NAV with fee accruals, run release checks | Deterministic engine | Figures that go to clients cannot depend on a model |
| Size each case's NAV impact, flag material ones | Deterministic engine | Prioritisation must be explainable and repeatable |
| Age open cases, escalate, track SLAs, clear on later matches | Deterministic engine | The multi-day workflow is a control, not a judgement |
| Suggest the cause of each break | Rules **and** AI | The AI reads the narrative text and context the rules cannot weigh |
| Explain the break, plan the investigation, draft the query | AI (rules as fallback) | Writing this up is where analysts spend their time |
| Approve, reject or reclassify; sign off the day | People | Accountability stays with the team |
| Record every action and every AI call | Hash-chained audit log | Tamper-evident trail for audit and model risk |

The AI never touches a figure, never raises or closes a case and never changes
the NAV. It only explains, suggests and drafts. That keeps the numbers exactly
reproducible while the slow, judgement-heavy part of the job gets faster.

## AI-assisted triage

For each case the engine assembles the evidence: the breaks with book and
custodian figures, the security, the related trades, settled and pending
custodian cash lines with their narrative text, pre-computed differences and
ratios, and the rule-based suggestion. The model returns structured JSON:

```json
{
  "category": "TIMING",
  "confidence": 0.9,
  "explanation": "Trade T2611130041 for 1,900 units was due to settle on 2026-11-13 ...",
  "investigation_steps": ["Check the custodian's failed-trades report ...", "..."],
  "custodian_query": "Subject: Unsettled trade T2611130041 ..."
}
```

Before anyone sees it, the response passes four guardrails:

1. **Schema.** It must match a strict JSON schema, and the category must be one
   of the existing causes. Anything else is rejected.
2. **No invented figures.** Every number in the explanation must trace back to
   the evidence the model was given (rounding allowed). A single unsupported
   figure rejects the whole response.
3. **Disagreement is surfaced, not resolved.** If the model disagrees with the
   rules, both suggestions are kept and the case is flagged
   *"AI disagrees: needs review"*.
4. **Safe fallback.** On any error, timeout, invalid response or missing API
   key, the case keeps its rule-based output and the run carries on.

Every call is written to the audit log with the model, a hash of the prompt,
the raw response and whether the fallback was used. Responses are cached on disk
by prompt hash, so evaluation runs are reproducible and cost nothing to repeat.

Anthropic, OpenAI and Google models are supported through their HTTP APIs, with
no SDK dependencies.

## Results

The data generator plants known breaks and writes an answer key, so the whole
pipeline can be scored. Over 20 business days with 200 planted breaks on the
**hard** data set (seed 42, medium reasoning effort):

| | Rules only | AI (gpt-6-luna) | AI (gemini-3.8-flash) |
|---|---|---|---|
| Breaks detected | 190/200 (95.0%) | 190/200 (95.0%) | 190/200 (95.0%) |
| Correct cause (of detected) | 178/190 (93.7%) | 190/190 (100.0%) | 190/190 (100.0%) |
| False alarms | 8/198 (4.0%) | 8/198 (4.0%) | 8/198 (4.0%) |
| Correct: late settlement (TIMING) | 21/33 | 33/33 | 33/33 |
| AI responses accepted by guardrails | n/a | 198/198 | 198/198 |
| Disagreed with rules (AI right / rules right) | n/a | 12 (12 / 0) | 12 (12 / 0) |

What this does and does not show:

- **Detection and false alarms are identical by design.** The AI explains the
  cases the engine raises; it does not find new ones.
- **All 12 gains are late settlements the custodian did not report as
  pending.** The rules read these as missing trades; both models read the trade
  and settlement dates and called them late. The prompt's definition of a
  timing break explicitly covers an unreported settlement, so part of the gain
  comes from that definition. In real life an unreported trade can genuinely be
  missing, which is why every disagreement goes to an analyst.
- **The 8 false alarms are dividends posted with no security identifier.** Both
  models correctly labelled all 8 as dividends where the rules said UNKNOWN,
  but the scorer matches cases to planted breaks by security, so they still
  count against both. Tying the payment to the right holding needs information
  the custodian did not send.
- The rules and the generator were written together, and the data is
  synthetic, so these are measures of consistency on known patterns, not of
  accuracy on real statements. On the standard data set the rules alone score
  100% on every measure.

Over 20 consecutive business days on the same hard data, with every open case
re-assessed each day (`reconpilot evaluate --multi-day --hard --ai`):

| | Rules only | AI (gpt-6-luna) |
|---|---|---|
| Detected on the day they appeared | 190/200 (95.0%) | 190/200 (95.0%) |
| Cause right on the first day | 178/190 (93.7%) | 189/190 (99.5%) |
| Cleared automatically on the fix day | 160/167 (95.8%) | 160/167 (95.8%) |
| Cause right at resolution | 157/160 (98.1%) | 160/160 (100.0%) |
| AI responses accepted by guardrails | n/a | 597/598 |

Cases carried from one day to the next keep the trade they came from, so the
AI is as accurate on them as on new ones: on an 8-day hard run (seed 21) it
named the right cause on 44/44 new and 75/75 carried cases, against the rules'
41/44 and 74/75, and every disagreement with the rules was flagged for review
(`scripts/ai_carried_check.py`).

Full tables and confusion matrices: [docs/evaluation.md](docs/evaluation.md).

## The deterministic engine

- **Matching.** Positions are compared on quantity and price. Cash is matched
  in passes, strictest first: exact reference and amount, reference within
  tolerance, security and amount when the reference is blank, and many-to-one
  when the custodian nets several trades into one line.
- **Rule-based triage.** Breaks on the same security form one case. Rules
  suggest a cause with a confidence score, explanation and draft query; this is
  also the fallback whenever the AI is unavailable.
- **NAV and release checks.** Stale prices, missing prices, NAV movement against
  a threshold, and a cash tie-out showing how much of the gap open breaks
  explain.
- **Review and sign-off.** Analysts approve, reject (with a reason) or
  reclassify each case. Only an approver can sign off the day, and not one who
  reviewed any case (four-eyes rule). Viewers can read but not act.
- **Audit log.** Each entry carries the SHA-256 hash of the one before, so an
  edited, deleted or reordered line is detected by `reconpilot verify-audit`.
- **Excel exception report.** Summary, exceptions with both the rule-based and
  AI suggestions side by side, raw breaks, cash matching, NAV checks and MI.

## The operations workflow across days

A reconciliation is not finished when the day's report is printed; breaks are
worked over days until they clear. Point `run` at the same `--out` folder every
day and ReconPilot keeps the fund's history there.

- **NAV impact and materiality.** Every case gets its net effect on NAV if the
  custodian's view is right (position market value plus cash), its size in
  basis points of NAV and its gross exposure. The queue and the report are
  sorted by impact. Cases at or above the materiality threshold (default 1 bp,
  `--materiality-bp`) are material: they block NAV release until approved or
  reclassified.
- **Carried items and automatic clearing.** Cash items left unmatched are fed
  back into the next day's matching, so a late settlement that arrives today
  matches yesterday's book item. A case whose breaks have gone is cleared
  automatically, with an audit entry. A booked trade the custodian settles late
  is recorded as resolved as a late settlement, whatever it looked like on day
  one.
- **Ageing, escalation and SLAs.** Open cases keep their identifier and age in
  business days, bucketed 0-1, 2-5 and >5. Material cases, and cases open
  longer than `--escalate-after` days (default 5), are escalated with an audit
  entry and need an approver's decision before sign-off. Cases open longer
  than their SLA (`--sla-material` 2 days, `--sla-other` 5 days) are reported
  as breaches.
- **Pricing controls.** The book-versus-custodian price tolerance is set per
  asset class (equities 25 bp, bonds 10 bp), and a day-on-day check flags
  prices that moved more than 10% (equities) or 2% (bonds) since the prior
  day, which catches bad prices and corporate actions applied on one side.
- **Accruals.** The NAV accrues the management fee (on the prior NAV) and
  other expenses daily, covering weekends on Mondays, and a release check
  fails on a missed accrual.
- **Management information.** An MI sheet in the report shows open breaks by
  cause and age with their NAV impact, average days to resolve, the top five
  cases by impact, SLA breaches and the trend over recent days. Each run also
  writes `mi.csv` in tidy long form (`as_of, metric, cause, age_bucket, value`)
  for Tableau or any other BI tool.

The multi-day evaluation runs one fund for 20 consecutive business days with
10 new breaks a day, each fixed 1 to 6 days later, and checks that every case
clears on the day the data agrees again:

| | Standard data | Hard data |
|---|---|---|
| Detected on the day they appeared | 200/200 (100.0%) | 190/200 (95.0%) |
| Cause right on the first day | 200/200 (100.0%) | 178/190 (93.7%) |
| Cleared automatically on the fix day | 169/169 (100.0%) | 160/167 (95.8%) |
| Cleared before the data was fixed | 0 | 0 |
| Cause right at resolution | 169/169 (100.0%) | 157/160 (98.1%) |
| Average business days to resolve | 3.17 | 3.16 |

On hard data, a third of the late settlements look like missing trades on the
day they appear (the custodian reports nothing pending). When they settle, the
case clears and is recorded as a late settlement, so all 30 are right at
resolution: the same weakness the AI fixes on day one, fixed instead by time.
The 7 breaks that do not clear on their fix day are dividends posted with no
security identifier, which are grouped together and clear only when all of
them have been booked.

No real data is used anywhere. All funds, securities and statements are
generated.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run a sample day on the rules alone:

```bash
reconpilot demo --dir demo
```

Run a working week, with breaks that age, escalate and clear:

```bash
reconpilot demo --dir demo-week --days 5
```

```
2026-11-13: 34 cash matches, 15 breaks, 11 open cases (4 new), 4 cleared automatically
  cleared EX-20261112-007  US0000806780   PRICE_MISMATCH  after 1 business day(s)
  cleared EX-20261109-002  GB0000678257   MISSING_TRADE   after 4 business day(s)
  ...
Review queue, largest NAV impact first (M material, E escalated, S SLA breached):
 ME  EX-20261111-002  US0000075627       383,603.04   +8.52bp  age  2  PENDING      PRICE_MISMATCH  0.85
 MES EX-20261110-004  US0000344774      -276,346.20   -6.14bp  age  3  PENDING      PRICE_MISMATCH  0.85
     EX-20261110-007  US0000353195        41,888.14   +0.93bp  age  3  PENDING      DIVIDEND        0.90
  ...
  [PASS] Day-on-day price moves
  [PASS] Accruals
  [FAIL] NAV release
```

Run it with AI-assisted triage. Set one key; the first one found is used, in the
order Anthropic, OpenAI, Google:

```bash
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY / GOOGLE_API_KEY
reconpilot demo --dir demo --hard --ai
```

```
AI triage: openai / gpt-6-luna (effort medium)
2026-11-13: 30 cash matches, 18 breaks, 12 open cases (12 new), 0 cleared automatically
  ...
     EX-20261113-011  (none)               2,841.57   +0.06bp  age  0  PENDING      UNKNOWN         0.30   AI: DIVIDEND 0.96  [AI disagrees: needs review]
     EX-20261113-004  JP0000512651        -1,728.45   -0.04bp  age  0  PENDING      MISSING_TRADE   0.70   AI: TIMING 0.84  [AI disagrees: needs review]
     EX-20261113-009  GB0000482048           -97.09   -0.00bp  age  0  PENDING      UNKNOWN         0.30   AI: FX_DIFFERENCE 0.96  [AI disagrees: needs review]
     EX-20261113-007  US0000275807            -0.03   -0.00bp  age  0  PENDING      STOCK_SPLIT     0.95   AI: STOCK_SPLIT 0.95
```

AI options, accepted by `run`, `demo` and `evaluate`:

| Option | Default |
|---|---|
| `--ai` | off: without it, or without a key, everything runs on the rules alone |
| `--ai-provider` | first of `anthropic`, `openai`, `google` with a key set |
| `--ai-model` | `claude-sonnet-5-5`, `gpt-6-luna` or `gemini-3.8-flash` |
| `--ai-effort` | `medium` (reasoning effort, where the provider supports it) |
| `--ai-cache` | `.reconpilot_cache/ai` |

## The daily workflow

```bash
# 1. Generate a week of data, one folder per business day (or use your own CSVs)
reconpilot generate --as-of 2026-11-09 --days 5 --breaks 4 --out data --hard

# 2. Each morning: reconcile into the fund's run folder, roll cases forward,
#    get the AI's second opinion, value the fund, write the report and mi.csv
reconpilot run --data data/2026-11-09 --out runs/fund1 --user priya --ai

# 3. Work the queue, largest NAV impact first
reconpilot queue --run runs/fund1
reconpilot review --run runs/fund1 --user priya --case EX-20261109-002 --approve
reconpilot review --run runs/fund1 --user priya --case EX-20261109-004 \
    --reclassify TIMING --note "custodian confirms failed delivery, settles T+1"

# ...or in bulk from a CSV with columns case_id,decision,category,note
reconpilot review --run runs/fund1 --user priya --decisions decisions.csv

# 4. Escalated (material or aged) cases need an approver's decision
reconpilot review --run runs/fund1 --user ann --role approver --case EX-20261109-001 --approve

# 5. A different approver releases the NAV
reconpilot signoff --run runs/fund1 --user tom --role approver

# 6. Check nobody has edited the audit trail (including the AI calls)
reconpilot verify-audit --run runs/fund1

# Next morning: same --out, and yesterday's cases carry over
reconpilot run --data data/2026-11-10 --out runs/fund1 --user priya --ai

# Score rules against AI, and the multi-day lifecycle
reconpilot evaluate --hard --ai
reconpilot evaluate --multi-day --hard
```

## Running the web application

The web application wraps the same engine for a team: built-in accounts and
roles, a PostgreSQL system of record, a job queue for runs, a server-side
release status, four-eyes sign-off and the hash-chained audit log in the
database, with a browser front end in `web/` (React, TypeScript and Vite) on
top of the API. Nothing needs Docker: development uses an embedded PostgreSQL
started from Python, and Node 20.19 or later for the front end.

```bash
pip install -e ".[dev,web]"
(cd web && npm install)
reconpilot-web dev
```

`reconpilot-web dev` starts the embedded database in `.rp_data/` (or uses
`RP_DATABASE_URL`), brings the schema up to date and, the first time, creates
the fund `DEMO1` (first business day 2026-11-09) and four users, printing
their one-time passwords once:

```
Created fund DEMO1 starting 2026-11-09 and these users. The passwords are shown once only; note them now:
  analyst1   analyst          ********************
  approver1  approver  admin  ********************
  approver2  approver         ********************
  viewer1    viewer           ********************
API on http://127.0.0.1:8000/api with a worker running in-process.
Front end on http://localhost:5173 (Vite, proxying /api to the API).
Ctrl+C stops everything.
```

It then serves the API on `127.0.0.1:8000` with a worker running in the same
process and, once `npm install` has been run in `web/`, Vite's dev server on
`localhost:5173`, which proxies `/api` to the API; open that address and sign
in. Ctrl+C stops the API, the worker, Vite and the database. For a single
server, build the front end once (`npm run build` in `web/`) and
`reconpilot-web serve` serves it from `web/dist` beside the API. A day is worked
through the API in the same order as on the command line: upload the files,
run, decide, sign off. Days go strictly in order, so the next business day can
be uploaded only once the previous one is signed off.

```bash
reconpilot generate --as-of 2026-11-09 --days 2 --breaks 4 --hard --out data
```

```python
from pathlib import Path

import httpx

def sign_in(user, password):
    c = httpx.Client(base_url="http://127.0.0.1:8000")
    c.post("/api/auth/login", json={"username": user, "password": password}).raise_for_status()
    c.headers["X-CSRF-Token"] = c.cookies["rp_csrf"]  # required on every POST
    return c

analyst = sign_in("analyst1", "<password printed by dev>")
approver = sign_in("approver1", "<password printed by dev>")
signer = sign_in("approver2", "<password printed by dev>")      # four-eyes: decides nothing
fund, day = "DEMO1", "2026-11-09"

files = [("files", (p.name, p.read_bytes(), "text/csv")) for p in Path(f"data/{day}").glob("*.csv")]
analyst.post(f"/api/funds/{fund}/days/{day}/files", files=files).json()   # {'status': 'validated', ...}
job = analyst.post(f"/api/funds/{fund}/days/{day}/run").json()["job_id"]   # 202: queued for the worker
analyst.get(f"/api/jobs/{job}").json()["status"]                         # 'done' a moment later

for case in analyst.get(f"/api/funds/{fund}/days/{day}/cases").json():   # largest NAV impact first
    who = approver if case["escalated"] else analyst                     # escalated cases need an approver
    who.post(f"/api/funds/{fund}/cases/{case['case_id']}/decision",
             json={"decision": "approve", "version": case["version"]})

signer.get(f"/api/funds/{fund}/days/{day}/release?for_user=me").json()  # ready, reasons, signable_by_me
signer.post(f"/api/funds/{fund}/days/{day}/signoff").json()["status"]  # 'signed_off'
signer.get(f"/api/funds/{fund}/days/{day}/audit").json()["chain_ok"]   # the day's audit trail: True
```

Whoever signs off must not have decided any of the day's open cases, so
`approver2` signs off the cases `approver1` decided. A viewer can read
everything and decide nothing.

| Command | What it does |
|---|---|
| `reconpilot-web dev [--host --port --start-date]` | Everything for development, as above |
| `reconpilot-web serve [--host --port]` | The API, and the built front end from `web/dist` when it exists |
| `reconpilot-web worker [--once]` | Run queued day runs (retried up to three times) |
| `reconpilot-web migrate` | Create or upgrade the schema and record the instance mode |
| `reconpilot-web create-user --username --role [--admin]` | Add an account (password from `RP_NEW_PASSWORD` or a prompt) |
| `reconpilot-web create-fund --code --name --start-date` | Add a fund with the engine's default settings |

| Variable | Meaning |
|---|---|
| `RP_DATABASE_URL` | PostgreSQL 15+ for the API and worker; empty means the embedded database |
| `RP_MIGRATION_DATABASE_URL` | The schema owner for `migrate` (default `RP_DATABASE_URL`) |
| `RP_MODE` | `real` (default) or `demo`; a database is written for one mode only |
| `RP_DATA_DIR` | Local state: the embedded database and AI cache (default `.rp_data`) |
| `RP_COOKIE_SECURE` | `1` behind HTTPS |
| `OPENAI_API_KEY` and the others | The AI provider, used only for funds with AI switched on |

`reconpilot-web migrate` creates an application role, `rp_app`, that can only
insert into and read the audit log; production runs the API and worker as that
role and migrations as the owner.

Front-end checks, run in `web/`: `npm run typecheck`, `npm run lint` and
`npm test -- --run` (Vitest with Testing Library).

## Input files

| File | Contents |
|---|---|
| `book_trades.csv` | Fund's trades: id, dates, security, side, quantity, price, currency, FX rate, fees, settlement cash |
| `book_positions.csv` | Fund's positions with price and price date |
| `custodian_holdings.csv` | Custodian's holdings statement |
| `custodian_cash.csv` | Custodian's cash statement in base currency, with narrative, including lines value-dated in the future |
| `securities.csv`, `fx_rates.csv`, `fund.csv` | Static data with asset class, rates, opening cash, prior NAV, shares in issue, fee rate and expense budget |
| `book_cash.csv` | Non-trade cash booked by the fund: income, FX adjustments (optional) |
| `accruals.csv` | Fee and expense accruals booked for the day (optional) |
| `prior_prices.csv` | Book prices on the prior business day, for the price move check (optional) |
| `planted_breaks.json` | Answer key (generated data only), with start and fix dates in multi-day data |

A run folder holds `run.json`, the hash-chained `audit.jsonl`, today's
`cases.json`, one `exceptions_<date>.xlsx` per day, `mi.csv`, and
`state/<date>/` with each day's case ledger and carried open items.

## Project layout

```
src/reconpilot/
  ai.py          AI triage: evidence, prompt, providers, guardrails, cache
  generator.py   synthetic days with planted breaks
  sequence.py    consecutive days for one fund, with breaks that persist until fixed
  matching.py    position and cash matching, per-asset-class tolerances, carried items
  triage.py      grouping breaks into cases, rule-based causes, draft queries
  impact.py      NAV impact, materiality and the NAV release check
  ledger.py      cases across days: ageing, escalation, SLAs, auto-clearing
  pipeline.py    one business day through the whole pipeline
  nav.py         NAV with accruals, release checks, price move and accrual checks
  mi.py          management information and the tidy mi.csv
  review.py      approve / reject / reclassify, roles, four-eyes sign-off
  audit.py       hash-chained audit log
  report.py      Excel exception report
  evaluate.py    scoring against the answer key, rules versus AI
  storage.py     CSV and JSON reading and writing
  cli.py         command line
src/reconpilot_web/
  app.py         FastAPI application: security headers, CSRF on every change
  auth.py        accounts, sessions, roles and lockout
  funds.py       funds, settings and the business calendar
  days.py        upload, validation and day status; queuing runs
  validation.py  file checks before any run
  jobs.py        PostgreSQL job queue and worker
  runner.py      a day through the engine, persisted in one transaction
  cases.py       case queue, detail and decisions
  release.py     release status and four-eyes sign-off
  auditlog.py    the hash-chained audit log in PostgreSQL
  cli.py         reconpilot-web: dev, serve, worker, migrate, create-user, create-fund
scripts/         the common-password list generator and the AI carried-case check
tests/           unit and end-to-end tests; AI tests use a fake client, no network
tests/web/       the web layer against an embedded PostgreSQL, including CLI equivalence
```

Run the tests with `pytest`. No API key is needed.

## Limitations and next steps

- One fund, one base currency (USD). Bonds are priced per unit, with no
  accrued interest, and there are no multi-currency cash accounts.
- Cases are tracked across days by security, so two unrelated breaks on the
  same security share one case, and payments with no security identifier are
  pooled into a single case.
- NAV impact assumes the custodian's view is right. When the book is right,
  the impact is the same size with the opposite sign, which is why it is used
  for ranking and materiality, not as a correction.
- In the multi-day simulation the book writes off the custodian's few-cent
  rounding each day; a live fund would post those write-offs explicitly.
- The AI sees one case at a time. It cannot attach an unidentified payment to a
  holding when the custodian sends nothing to link them.
- The evaluation is on synthetic data the rules were designed alongside, with
  200 breaks; 100% on 190 detected cases is a strong result on known patterns,
  not a claim about production accuracy.
- The figure check stops invented numbers in the explanation, not wrong
  reasoning about correct numbers. That is what the human review is for.
- Sending evidence to an external model is a data-governance decision. Here the
  data is synthetic; a real deployment would need an approved provider or a
  privately hosted model.
- Cases are matched to the answer key by security, so a break spanning two
  securities would be scored as two.

- With `--ai`, open cases are re-assessed every day, and a carried case whose
  evidence changes costs a new call (598 calls over the 20-day evaluation).

Planned: AI extraction of corporate-action notices checked against the
custodian, per-currency cash accounts, and measuring analyst time per case
with and without the AI's write-up.

## Licence

MIT
