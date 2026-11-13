# ReconPilot web application: design

Date: 13 November 2026
Status: approved by the owner, 13 November 2026

## 1. Intent

ReconPilot is a portfolio project, built to show a fund-servicing team (the
owner is applying to J.P. Morgan's Fund Servicing) that its author understands
their daily work and can build the tools for it. The engine already exists as
a Python library with a command line and an Excel report. This project gives
it a web application.

Two things matter, in this order:

1. **A public demo that impresses in two minutes.** A recruiter or hiring
   manager opens a link, signs in with one click as an analyst or approver,
   and works a realistic morning: breaks ranked by NAV impact, AI explanations
   with drafted custodian queries, four-eyes sign-off, MI, a verifiable audit
   trail. No installation.
2. **Features an operations team would recognise as theirs**: NAV impact and
   materiality, ageing and escalation, SLAs, automatic clearing, maker-checker
   sign-off, a tamper-evident audit log, MI with export. It must also work
   properly when run locally with real files, because "it actually works" is
   part of what impresses.

What a user must come away with: confidence that every break is found,
explained, owned and signed off, with nothing slipping through.

Roles: **analyst** (works breaks), **approver** (decides material and escalated
cases, signs off the NAV), **viewer** (read-only, MI). An **admin** flag on a
user allows user and fund administration.

## 2. Goals, non-goals, anti-goals

**Goals**

- A working end-to-end slice early: upload, run, queue, decide, sign off.
- The six core screens: morning overview; upload and run; case workbench;
  sign-off; MI with exports; audit log with chain verification. Plus sign-in.
- Built-in accounts with roles, enforced on the server.
- PostgreSQL as the system of record, across days and several funds.
- A public demo where each visitor gets their own fund.
- Calm, dense, precise; subtle motion; keyboard shortcuts; WCAG 2.2 AA.
- Tests in every phase, then an independent code review.

**Non-goals**

- Docker (dropped by the owner).
- Single sign-on, regulated-grade deployment (high availability, point-in-time
  recovery, log shipping). Noted as future work in the README.
- Live custodian feeds (SWIFT, ISO 20022). Files are uploaded.
- Mobile layouts. This is a desk tool.

**Anti-goals: failure even if it technically works**

- A break in the data that is not an open case, or a case that disappears
  without an audit entry.
- A control enforced only in the browser.
- A screen that contradicts itself (for example "release blocked" next to a
  passing release check).
- Demo and real data in the same database.
- The AI deciding anything, or quoting a figure that is not in the evidence.
- Results that differ from the command line for the same files.
- Polish before function: nothing is styled until the slice works.

## 3. Constraints

- The engine (`src/reconpilot/`) stays the core. New code calls it; the
  engine never imports the web layer. Engine changes are limited to those in
  section 9 and keep every existing test passing.
- No Docker. Everything runs natively on Windows, macOS and Linux: a Python
  virtual environment, an embedded PostgreSQL started from Python
  (`pgserver`, a Python dependency, so nothing to install system-wide), and
  the Vite dev server. Production uses any PostgreSQL 15 or later through
  `DATABASE_URL`.
- No AI attribution in commits, PRs or docs.
- Provider API keys only on the server, from environment variables.

## 4. Approaches

### 4.1 Engine and database

| Approach | Trade-off | Verdict |
|---|---|---|
| **Engine as a library, PostgreSQL as the system of record**: the API stores the day's files, builds the engine's `DayData`, calls `pipeline.run_day` and persists the results | One source of truth, safe for concurrent users, engine untouched | **Chosen** |
| Keep run folders as the master copy, mirror them into PostgreSQL | Two copies of the truth; file races between users | Rejected |
| Engine writes to the database itself | Couples the engine to the database; breaks the command line | Rejected |

### 4.2 Authentication

Built-in accounts first (owner's choice): argon2id passwords, server-side
sessions, roles on the server. Single sign-on is future work; `users` keeps a
nullable `external_subject` so it can be added without reworking roles.

### 4.3 Calls made on the owner's behalf

- **Stack**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3; React,
  TypeScript, Vite, TanStack Query and Table, Radix UI primitives for
  accessible dialogs and menus; styling with CSS custom properties.
- **Background jobs**: a small job table in PostgreSQL (`FOR UPDATE SKIP
  LOCKED`) and a worker process. Runs without AI take under a second; AI runs
  take minutes, so both go through the queue and the UI polls for progress.
- **One command**: `reconpilot-web dev` starts the embedded database, runs
  migrations, and launches the API, worker and Vite together.
  `reconpilot-web serve` runs the API serving the built front end, for the
  demo host.

## 5. Architecture

```
browser ──► front end (Vite in development; built files served by the API in production)
               │ /api
               ▼
            api (FastAPI) ──────────────┐
               │ enqueue                 │ read/write
               ▼                         ▼
            worker ─────────────────► PostgreSQL
               │ calls
               ▼
            reconpilot engine ── AI provider (server-side key, or a private endpoint)
```

The web layer is a new package, `src/reconpilot_web/` (api, worker, models,
adapters). The front end lives in `web/`.

## 6. Data model

Alembic migrations. Main tables:

- **instance_settings**: `mode` (`real` or `demo`), written once. The app
  refuses to start if its configured mode differs, so demo and real databases
  can never be mixed.
- **users**, **sessions**: accounts, roles, admin flag, lockout fields; hashed
  session ids with expiry.
- **funds**: code, name, base currency, start date, non-business dates,
  settings (materiality bp, escalation and SLA days, tolerances, price-move
  limits, AI on or off). Demo funds also record their visitor and expiry.
- **business_days**: per fund and date: status (`uploaded`, `validated`,
  `running`, `ready`, `signed_off`, `failed`), NAV figures, release status,
  who ran and who signed off.
- **input_files**: the original bytes with their SHA-256, per day.
- **cases**: keyed by (fund, case_id); current state as columns for queries,
  plus the engine's full `Case` as JSONB.
- **case_snapshots**: each case as it stood at the end of each day (the
  engine's daily ledger), for history, MI and the trend.
- **breaks**, **open_items**: the evidence per run, and the cash items carried
  to the next day.
- **decisions**: every human decision, with user, role, note and time.
- **audit_log**: the hash chain (section 8).
- **jobs**, **ai_cache**.

## 7. How a business day flows

1. **Upload** the day's CSVs (the set the engine already reads). Stored with
   their hashes.
2. **Validate before running**, shown per file and row: required files, exact
   headers, types, one as_of date matching the chosen day, security ids known,
   no duplicate ids, settle not before trade date, FX rates present, size
   limits. Errors block the run; warnings do not.
3. **Run** as a job: build `DayData`, attach the previous day's open items and
   open cases, call `pipeline.run_day` with the fund's settings, the
   database audit log and (if switched on for the fund) the AI.
4. **Persist** in one transaction: cases, snapshots, breaks, open items, NAV,
   checks, release status.
5. **Order**: a day must be signed off before the next business day can be
   uploaded or run (owner's decision). So only the latest day can be re-run,
   and a re-run keeps decisions that still apply, voiding others with an
   audit entry. Each fund has a start date and a list of non-business dates.
6. **Equivalence test**: the same multi-day files through the command line and
   through the web pipeline give identical cases, figures and audit actions.

## 8. Audit log

- The engine's record format and SHA-256 chain, written to PostgreSQL through
  a database implementation of the engine's `append(actor, role, action,
  payload)`, so the engine's review and AI code write to it unchanged.
- Appends are serialised so the chain cannot fork.
- Append-only by permission: the app's database role can only INSERT and
  SELECT; a trigger rejects UPDATE, DELETE and TRUNCATE.
- Also records sign-ins, failures, lockouts, uploads, validation, runs,
  exports, user and fund changes.
- **Viewer**: filter by fund, date, actor, action or case; "Verify chain"
  re-checks every hash on the server. Export to CSV.

## 9. Controls, release status and engine changes

**Controls, all on the server**: roles from the session; viewers cannot act;
reject needs a note; escalated cases need an approver's decision; material
cases block release until approved or reclassified; four-eyes (whoever signs
off decided none of the day's open cases); sign-off locks the day; a stale
decision (someone else decided first) is refused, not overwritten.

**One release status**, computed on the server and shown identically
everywhere: *Ready* or *Blocked* with the list of reasons (pending decisions,
material cases awaiting approval, escalated cases awaiting an approver, failed
checks, four-eyes). The engine's own check, which covers material cases only,
is shown under its accurate name, "Material cases approved".

**Unlocking** a signed-off day (owner's decision): an admin requests it with a
reason and a different approver confirms; only the latest signed-off day,
before the next day runs; all audited. Built in the polish phase.

**Engine changes** (each with tests; defaults unchanged so the command line
behaves exactly as before):

1. *Carried-case evidence*: the AI evidence includes the original trade for
   references in carried items. Found in a sample run, where a carried FX case
   lost its context and the AI answered UNKNOWN.
2. *Number formatting in evidence*: quantities are passed as whole numbers
   where they are whole, so the AI quotes "25,900", not "25900.0".
3. *Settings pass-through*: `pipeline.run_day` accepts optional check
   settings (price-move limits, NAV movement threshold, cash tolerance) so
   fund settings reach every check.
4. *Private AI endpoint*: an OpenAI-compatible client with a configurable base
   URL (for example a bank's Azure OpenAI), alongside the existing providers.
   In real mode AI is off for every fund until an admin switches it on, with a
   warning; the switch is audited.
5. *Disagreement flag on carried cases*: when a carried case keeps an earlier
   diagnosis, the "AI disagrees: needs review" flag is recomputed against it.
   Today the flag is set before the diagnosis is restored, so a real
   disagreement can go unflagged.

**Measured before the build** (8-day hard run, gpt-6-luna, seed 21): on the day
a case first appears the AI named the right cause **44 of 44** times against
the rules' 41. On carried cases (day two onwards) it fell to **54 of 75**
against the rules' 74, because of change 1, and **20 disagreements went
unflagged**, because of change 5. Acceptance for phase 1: on the same run the
AI is at least as accurate on carried cases as on new ones, every disagreement
is flagged, and `docs/evaluation.md` gains a rules-versus-AI multi-day table.

**AI features carried into the web app unchanged**: the second opinion beside
the rules, the schema and invented-figure guardrails with fallback to the
rules, investigation steps, the draft custodian query, the disagreement flag,
every call in the audit log with model, prompt hash and response, and the
response cache. The escalation reason records the NAV impact at the time of
escalation; the UI labels it "at escalation" so it is not confused with
today's impact.

## 10. Screens and look

**Visual direction**: a combination of the three mockups in
`docs/design/mockups/`:

- **C's workbench** for case work: queue, case and evidence panes that stay
  put, the decision bar always in reach, a command palette (Ctrl+K). The
  evidence pane collapses or widens for long AI text.
- **B's sticky NAV strip** on every screen: NAV, NAV per share and movement,
  the release status, and the sign-off entry point.
- **A's overview and sign-off**: the "every break accounted for" table (found,
  held in a case, decided, pending) and the audit trail shown at sign-off.
- **Night desk palette, dark first** (owner's choice): deep slate surfaces
  (`#131B26` background, `#18222F` panels, `#243243` raised), light ink
  (`#E2E8F0`), a blue accent for links, focus and selection, and Night desk's
  orange-amber (`#F2B54B`) as the one signal colour meaning "needs you".
  Restrained green and red, always with an icon or word. A light theme exists
  for accessibility but dark is the default.
- **Uncluttered** (owner's feedback): one job per screen, the most important
  thing first, detail on demand (expanders, the evidence pane, tooltips)
  rather than everything at once. Fewer panels, more space between groups,
  no decorative statistics.
- **Live data only**: every figure on every screen comes from the API. No
  figure from the mockups or sample files is baked into the front end.

**Screens**

1. **Morning overview**: NAV strip; release status with reasons; every break
   accounted for; open breaks by NAV impact (**gross and net** shown, never
   net alone); ageing buckets; SLA breaches; escalations; cleared today; trend.
2. **Upload and run**: drop zone, validation results before running, progress,
   run history.
3. **Case workbench**: filters (cause, status, material, escalated, SLA, age,
   AI disagreement) and search; book versus custodian evidence; rule
   suggestion beside the AI second opinion; investigation steps; draft query
   with copy; decision history; decision bar.
4. **Sign-off**: release conditions, who decided what, the audit trail, the
   sign-off action and its blocked states in plain words.
5. **MI**: breaks by cause and age with impact, time to resolve, trend, top
   five, SLA breaches; export to Excel and `mi.csv`.
6. **Audit log**: section 8.
7. **Sign-in**; **admin** pages for users and funds (polish phase).

**One vocabulary**, defined once in the front end and used in exports:
causes (Missing trade, Late settlement, Price mismatch, Stock split, Dividend,
FX difference, Unexplained) and statuses (Pending, Approved, Rejected,
Reclassified, Cleared).

**Keyboard**: j/k and arrows, Enter, a approve, r reject, c reclassify,
/ search, g then o/u/q/s/m/l for screens, Ctrl+K palette, ? help, Esc. Never
while typing. **Motion**: list entry, pane transitions of 150 to 200 ms,
figure tweens, the release status changing; all off under reduced motion.
**Accessibility**: WCAG 2.2 AA in both themes; semantic tables; labelled
controls; focus management; status never by colour alone; flags are labels,
not tiny buttons; usable at 200% zoom.

## 11. Demo mode

- A separate instance with its own database (`reconpilot-web serve --mode
  demo`); its upload endpoint is disabled on the server.
- **"Try the demo"** creates a fund for that visitor by running the engine's
  sequence generator from a fixed seed: a hard-mode working week, with the
  week's earlier days already reviewed and signed off and the last day waiting.
  It reuses the multi-fund support, so there is no copying machinery. The
  visitor gets four one-click users (analyst, two approvers to show four-eyes,
  viewer) and a role switcher. Nothing is shared between visitors.
- "Generate the next business day" lets a visitor carry on.
- AI answers come from a pre-filled cache built from the same seed, so the
  demo needs no API key and costs nothing; anything not cached falls back to
  the rules.
- Visitor funds expire 24 hours after last use; a cleanup job deletes them.
  Creation is rate-limited and the number of live demo funds is capped.
- A permanent banner says the data is synthetic.

## 12. Security

argon2id passwords (minimum 12 characters, common-password check); lockout
after repeated failures; hashed session ids in httpOnly, Secure, SameSite=Lax
cookies with idle and absolute timeouts; CSRF tokens on every state change;
rate limits on sign-in, runs and exports; authorisation checked on every route
with tests per role; strict Content-Security-Policy and security headers;
uploads limited in size and parsed defensively; SQL only with bound
parameters; secrets from the environment, documented in `.env.example`;
pip-audit and npm audit in CI.

## 13. Testing

- Engine: the existing 95 tests unchanged, plus tests for the four engine
  changes.
- API: pytest against a real PostgreSQL started by the tests through
  `pgserver`: roles on every route, fund access, sign-off order, four-eyes,
  material blocking, release status, locking, stale decisions, audit
  append-only (UPDATE and DELETE attempts must fail), chain verification,
  validation, demo isolation, the equivalence test.
- Worker: job claiming under concurrency, failures recorded.
- Front end: Vitest and Testing Library; Playwright journeys per role; axe
  accessibility checks on every screen in both themes.
- GitHub Actions runs everything natively.

## 14. Phases

Each phase ends with its tests passing and a commit.

1. **Backend slice**: `reconpilot-web dev`, embedded database, migrations,
   users and sessions with roles, database audit log, one fund, upload,
   validation, job queue and worker, run, cases, decisions, single release
   status, sign-off with four-eyes, day ordering, the equivalence test, engine
   changes 1 to 3.
2. **Front-end slice**: sign-in, NAV strip, overview, case workbench, decision
   bar, sign-off, in the combined visual direction, with the keyboard basics.
   At the end of this phase a person can work a whole day in the browser.
3. **The rest of operations**: several funds and fund switching, upload and
   run screen with validation display, MI with exports, audit log viewer,
   multi-day history and trend.
4. **Demo mode**: visitor funds from the generator, one-click users, cached AI,
   expiry, banner; serving the built app from the API for a single demo host.
5. **Polish**: command palette, motion, full shortcut set, accessibility pass,
   admin pages for users and funds, AI per-fund switch and private endpoint
   (engine change 4), unlocking, security hardening, performance with a year
   of history.
6. **Independent code review** by a separate reviewer, then fixes.

**Future work** (README only): single sign-on, a production hosting kit with
HTTPS and backups, regulated-grade deployment, live custodian feeds, AI
extraction of corporate-action notices.

## 15. Left to the builder

Component and file structure; polling intervals; whether snapshots store full
ledgers or deltas (as long as history is exact); pagination and indexes; any
small animation library; where the demo is hosted (any host that runs Python
and PostgreSQL).
