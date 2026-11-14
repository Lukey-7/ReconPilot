# Phase 3: The Rest of Operations Implementation Plan

**Goal:** Everything a fund-servicing desk needs beyond a single day's slice: several
funds and switching between them, the full upload and run screen, MI with exports, the
audit log viewer, and multi-day history and trend.

**Spec:** `docs/superpowers/specs/2026-11-13-reconpilot-web-app-design.md` (sections 7, 8,
10 and phase 3 of section 14). Phases 1 and 2 are the base; their route, field and
component names are not changed here. New fields are only ever added to existing
responses, never renamed or removed.

**Stages:** 3a funds and the upload screen (this section). Later stages (MI with
exports, the audit log viewer, multi-day history and trend) add their own sections below.

## Global constraints

The phase 2 constraints stand: live data only, one vocabulary (`web/src/vocabulary.ts`),
status never by colour alone, controls enforced on the server, shortcuts never while
typing, motion off under reduced motion. Before every commit: `pytest -q` at the root, and
`npm run typecheck`, `npm run lint`, `npm test -- --run --no-file-parallelism` in `web/`.
Playwright runs with `--workers=1` and Chromium only.

---

## Stage 3a: funds and the upload screen

### Backend

#### The fund each user works: `GET` / `PUT /api/auth/me/preferences`

Any signed-in role; `PUT` needs the CSRF token like every state change.

```json
{"fund": "GEF1"}
```

`fund` is the code of the fund the user last chose in the fund selector, or `null`.
`PUT {"fund": "INC2"}` stores it (404 for an unknown fund) and answers with the stored
preferences; `PUT {"fund": null}` clears it. Stored in `users.preferred_fund_id`
(migration `0002`, a nullable foreign key to `funds` with `ON DELETE SET NULL`, so a
removed fund simply clears the choice). `GET /api/auth/me` is unchanged.

A preference is a convenience, not a control, so it is not audited.

#### A fund's settings in force: `GET /api/funds/{code}` gains `checks_in_force`

The release checks' settings as the engine will apply them for this fund: the engine's
defaults (`nav.run_checks` and `nav.PRICE_MOVE_LIMITS`) overlaid by the fund's
`check_settings`:

```json
{"max_price_age_days": 1, "movement_threshold": 0.02, "cash_tolerance": 1.0,
 "price_move_limits": {"EQUITY": 0.10, "BOND": 0.02}}
```

#### Whether a day can take files: `GET /api/funds/{code}/days/{as_of}/intake`

Any signed-in role. Answers for any date, loaded or not, so the screen can say in plain
words why a day cannot be loaded before anyone tries.

```json
{
  "fund": "GEF1", "as_of": "2026-11-11",
  "open": false,
  "blocked": {"code": "PREVIOUS_NOT_SIGNED_OFF", "message": "Sign off 2026-11-10 first.",
              "day": "2026-11-10", "day_status": "ready"},
  "day_status": null,
  "previous_business_day": "2026-11-10", "previous_status": "ready",
  "following_day": "2026-11-12",
  "expected_files": [{"kind": "securities", "filename": "securities.csv", "required": true}],
  "max_file_bytes": 5242880, "max_rows": 200000
}
```

- `open` is true exactly when an analyst or approver's upload for the day would pass the
  day-order and lock checks (`blocked` is then `null`).
- `blocked.code`, in the order checked: `UPLOADS_OFF` (demo instance), `BEFORE_START`,
  `NOT_BUSINESS_DAY`, `PREVIOUS_NOT_LOADED` (the previous business day has no files),
  `PREVIOUS_NOT_SIGNED_OFF`, `SIGNED_OFF` (the day itself is locked), `RUNNING`.
  `blocked.day` is the date the reason is about (the previous day, the start date, or
  the day itself) and `day_status` that day's status. `message` is the server's own
  wording, identical to the 409 the upload route gives for the same reason.
- `following_day` is the business day after `as_of`: what opens once `as_of` is signed off.
- `expected_files` lists every file the engine reads, in the engine's order, with
  whether a run needs it, so the screen can show per file what is held and what is missing.

`days.check_day_order` keeps its behaviour and messages; it now raises from the same
`day_order_problem` function the intake route reports.

#### The day's runs: `GET /api/funds/{code}/days/{as_of}/runs`

Any signed-in role; 404 when the day has no files. Every `run_day` job for the day, newest
first:

```json
{
  "fund": "GEF1", "as_of": "2026-11-10",
  "runs": [{
    "job_id": 12, "status": "done", "attempts": 1, "max_attempts": 3,
    "started_by": "analyst1", "rerun": false,
    "queued_at": "...", "started_at": "...", "finished_at": "...", "duration_seconds": 0.8,
    "error": null,
    "outcome": {"open_cases": 6, "new_cases": 4, "carried_cases": 2, "cleared_today": 1,
                "breaks": 9, "matches": 120,
                "decisions_reapplied": 0, "decisions_voided": 0, "cases_withdrawn": 0},
    "skipped": null
  }]
}
```

`rerun` comes from the run's `RUN_STARTED` audit entry; `outcome` from the job's result
(the run summary; `null` until the run is done); `skipped` is the worker's reason when a
stale job found the day no longer waiting to run.

### Front end

- **Fund switching** (`shell/workspace.tsx`): the fund comes from the address, else the
  user's stored preference (`usePreferences`), else the first fund. Choosing a fund in the
  selector stores it for the user (`useSetPreferredFund`) so it follows them to another
  browser; a fund opened from a shared link is not stored. The browser-local memory of
  phase 2 is replaced by the per-user preference.
- **Funds screen** (`/funds`, `g f`, and a "Funds" link beside the fund selector): every
  fund with its latest day and status, and the chosen fund's settings read-only:
  materiality, escalation and SLA days, the AI second opinion, the release checks in
  force and the business calendar. A line says settings are changed by an administrator.
- **Upload and run** (`screens/upload/`), per spec section 10, screen 2:
  - when the day cannot take files, the reason in plain words first (for the previous day
    not signed off: which day, its status, and a link to its sign-off), and no drop zone;
  - the drop zone takes several files at once; names ReconPilot does not read are listed
    and not sent;
  - per expected file: held or missing, size, who uploaded it, and its validation result;
    each file's errors and warnings by row, on demand; errors block the run;
  - the run as a short sequence (queued, running, finished) polled from the job, with the
    attempt when a retry is under way;
  - the day's run history (`useDayRuns`);
  - for a ready day that is not signed off, which day opens next and that it opens once
    this one is signed off.

### Tests

- pytest: `tests/web/test_preferences.py` (stored per user, survives a new session,
  unknown fund 404, CSRF needed, cleared when the fund is removed, viewers may set it);
  `tests/web/test_intake.py` (every block code, `open` agreeing with the upload route,
  expected files, following day; runs listed newest first with outcome, failure and
  re-run); `tests/web/test_funds.py` gains `checks_in_force`.
- Vitest: workspace preference (stored preference wins over the first fund, the address
  wins over the preference, switching stores it); `FundsScreen`; the upload screen's
  previous-day message, per-file validation, ignored names, run progress and history.
- Playwright (`e2e/funds-and-upload.spec.ts`, its own throwaway database as in phase 2,
  with a second fund): the previous-day message, switching funds and the choice following
  the user into a new session, the funds screen read-only, and axe on both new views.

---

## Stage 3b: MI and exports

Spec section 10, screen 5: breaks by cause and age with impact, time to resolve, the trend,
the top five and SLA breaches, with exports to Excel and `mi.csv`.

### The ledger across days

The command line keeps, for every run day, a ledger of every case seen so far: the cases
cleared on any earlier day, the cases cleared that day and the cases still open
(`ledger.save_ledger`). The engine's MI (`mi.build_mi`, `mi.mi_rows`) is computed from those
ledgers. The web layer stores only each day's own cases in `case_snapshots` (the cases
cleared that day and the cases still open), so `reconpilot_web.mi.ledger_history` rebuilds
the command line's ledgers from them: for run day `d`, every case cleared on a run day up to
`d` (in clearing order, each clearing day largest absolute impact first, as the engine rolls
them forward) followed by `d`'s open cases (largest absolute impact first). A run day is a
day with a finished run whose status is `ready` or `signed_off`, as for the overview.

The overview's trend uses the same ledgers, so its average time to resolve now covers every
case cleared so far, as the command line's MI sheet does, instead of only the day's own
clearings. Every other trend figure is unchanged.

### `GET /api/funds/{code}/days/{as_of}/mi`

Any signed-in role (viewers included); 404 when the day has no files. Computed with the
engine's `mi.build_mi` from the rebuilt ledgers (trend: at most 20 run days, oldest first).
Causes are the engine's current cause (`ledger.current_category`: resolved, else
reclassified, else the accepted AI cause, else the rules' cause) as enum values.

```json
{
  "fund": {"code": "GEF1", "name": "...", "base_currency": "USD", "materiality_bp": 1.0},
  "as_of": "2026-11-10", "day_status": "ready", "has_run": true, "run_days": 2,
  "by_cause_age": {
    "buckets": ["0-1", "2-5", ">5"],
    "rows": [{"cause": "TIMING", "count": 2, "net": 0, "gross": 0,
              "cells": [{"bucket": "0-1", "count": 1, "net": 0, "gross": 0}]}],
    "total": {"count": 0, "net": 0, "gross": 0, "cells": []}
  },
  "time_to_resolve": {"rows": [{"cause": "TIMING", "cleared": 3, "avg_days": 1.33}],
                      "all": {"cleared": 3, "avg_days": 1.33}},
  "top_open": [{"case_id": "...", "security_id": "...", "security_name": "...", "cause": "TIMING",
                "nav_impact": 0, "nav_impact_bp": 0, "age_days": 0, "material": false,
                "escalated": false, "sla_breached": false, "status": "PENDING"}],
  "sla_breaches": [{"case_id": "...", "security_id": "...", "security_name": "...", "cause": "TIMING",
                    "age_days": 0, "sla_days": 0, "material": false, "status": "PENDING",
                    "cleared_on": null}],
  "trend": [{"as_of": "...", "open_cases": 0, "new_cases": 0, "cleared_cases": 0, "material_open": 0,
             "escalated_open": 0, "sla_breaches_open": 0, "aged_over_5": 0, "open_nav_impact": 0,
             "open_gross_impact": 0, "avg_days_to_resolve": null}],
  "exports": {"report": "/api/funds/GEF1/days/2026-11-10/exports/report.xlsx",
              "mi_csv": "/api/funds/GEF1/days/2026-11-10/exports/mi.csv"}
}
```

- `by_cause_age` lists every cause with an open case (engine order) and every bucket; each
  cell, row and the total carry the count and the **net and gross** impact (gross: the sum
  of absolute impacts, so offsetting breaks cannot hide). Counts sum to the open cases.
- `time_to_resolve`: per cause, the cases cleared up to `as_of` and their average business
  days open (`ledger.days_to_resolve`); `all` across causes (`avg_days` null when none).
- `top_open`: the five open cases with the largest absolute NAV impact.
- `sla_breaches`: every case that has breached its SLA up to `as_of`, open ones first, then
  oldest; `cleared_on` is set for one that has since cleared.
- `trend` is the engine's `summarise_day` per run day, plus `open_gross_impact`.
- Before the day has run: `has_run` false, empty lists and zero counts, `exports` null,
  and `trend` still shows the earlier run days.

### Exports, audited

Both are `GET` (so a plain link works), any signed-in role, 404 for a day with no files and
409 for a day that has not finished a run. Each download writes `EXPORT_DOWNLOADED` to the
audit log with the fund and `{"as_of", "export": "exception_report" | "mi_csv", "filename",
"bytes", "sha256", "run_days"}`, in the same transaction that produces the file.

- `GET .../exports/report.xlsx`: the engine's `report.write_report` for the day, built as
  the command line's `_render` builds it: the day's stored files read by the engine with
  the previous day's open items attached, `reconcile` and `compute_nav` again (both are
  deterministic), the day's open cases, its checks with the release check under its
  accurate name and recomputed from the current cases (as every screen shows it), the
  signer's username, and the rebuilt ledgers for its MI sheet. File name
  `exceptions_{FUND}_{as_of}.xlsx`.
- `GET .../exports/mi.csv`: the engine's `mi.write_mi_csv` over every run day up to
  `as_of` (`as_of, metric, cause, age_bucket, value`), byte for byte what the command line
  writes for the same days. File name `mi_{FUND}_{as_of}.csv`.

Exports keep the engine's cause codes and column names, so they match the command line's
files and load into a BI tool unchanged; the screens use the vocabulary.

### Front end

- **MI screen** (`/mi`, `g m`, "MI" in the screen list), `screens/mi/`: the header carries
  the two export buttons (downloaded with `fetch`, so a refusal shows in plain words
  instead of a downloaded error page). Then, one block each and nothing decorative:
  open breaks by cause and age (counts per bucket, gross and net per cause, a total row;
  the impact per bucket behind an expander), the trend (a bar per run day for one chosen
  measure: open, new, cleared, material, escalated or past SLA; the figures behind an
  expander), time to resolve by cause, the top five open cases and SLA breaches. Case ids
  open the case in the workbench. A day not yet run says so and shows only the trend.
- `api/client.ts` gains `download(path)`; `api/queries.ts` gains `useMi` and `paths.mi`,
  `paths.exportReport`, `paths.exportMiCsv`; the vocabulary gains `EXPORT_DOWNLOADED` and
  the trend measures.

### Tests

- pytest `tests/web/test_mi.py`: sign-in, 404 and the not-run shape; counts summing to the
  open cases with gross and net per cell, row and total; time to resolve and SLA breaches
  across days including cases cleared on earlier days; top five; viewers may read and
  export; both exports audited with their hash; 409 before a run; the Excel workbook's
  sheets and the CSV's columns. `tests/web/test_equivalence.py` additionally checks, for
  every one of its five days, that the MI route agrees with the engine's `build_mi` over
  the command line's ledgers, that the exported workbook's cells equal the command line's
  workbook (but for the release check's accurate name), and that `mi.csv` is byte for
  byte the command line's.
- Vitest `screens/mi/MiScreen.test.tsx`: the matrix and totals, gross beside net, the
  trend measure switch, top five and SLA rows linking to cases, the not-run day, export
  downloads and an export refusal.
- Playwright `e2e/mi.spec.ts`: MI for a run day with both exports downloaded (the file
  names and the CSV header checked) and axe on the screen in both themes.

---

## Stage 3c: the audit log viewer and history across days

Spec section 8 (the viewer: filter by fund, date, actor, action or case; verify the chain
on the server; export to CSV) and the multi-day history of section 14, phase 3.

### The audit log: `src/reconpilot_web/auditviewer.py`, routes under `/api/audit`

Any signed-in role, viewers included (reading the log is how a control team checks the
desk). The chain is global, so entries without a fund (sign-ins, user creation, chain
verifications) are part of the log too.

**Filters**, shared by the list and the export, every one optional:

| Parameter | Meaning |
|---|---|
| `fund` | a fund code (404 for an unknown fund); absent means every entry, funds and system |
| `as_of` | one business day's trail, exactly as `GET .../days/{as_of}/audit` finds it; needs `fund` (422 without) |
| `from`, `to` | when the entry was recorded, inclusive: an ISO date (a whole UTC day) or an ISO date-time with an offset (the browser sends the user's local day as instants); 422 when `from` is after `to` |
| `actor` | a username, case-insensitive |
| `action` | one or more actions, comma-separated (`CASE_APPROVED,CASE_REJECTED`); 422 for anything that is not an action code |
| `case` | a case id, case-insensitive |

**`GET /api/audit`**: one page of matching entries, newest first, by keyset on `seq`.
`limit` 1 to 200 (default 50); `before` a sequence number (entries below it).

```json
{
  "entries": [{"seq": 41, "ts": "...", "actor": "approver2", "role": "approver",
               "action": "DAY_SIGNED_OFF", "fund": "GEF1", "case_id": null, "case_as_of": null,
               "payload": {"cases": 6}, "prev_hash": "...", "hash": "..."}],
  "total": 41, "newer": 0, "has_newer": false, "newer_before": null, "next_before": null,
  "latest_seq": 57
}
```

`total` counts every matching entry; `newer` how many match above this page (so the screen
says "51 to 100 of 1,234"); `next_before` is the cursor for the next older page (null on
the last page) and `newer_before` the cursor for the next newer page (null when that page
is the first; `has_newer` false when there is none). `latest_seq` is the whole log's
newest entry. Entries carry their payload (the screens word it from the vocabulary);
`fund` is the fund's code (null for system entries, or for a fund since removed) and
`case_as_of`, for an entry about a case, the latest day the case was in a run, so the
screen opens the case where it stands.

**`GET /api/audit/facets`** (optional `fund`): `{"actors": [...], "actions": [...]}`, the
distinct values present, sorted, for the filter menus.

**`GET /api/audit/entries/{seq}`**: one entry in full, with its own integrity:
`hash_ok` (its hash recomputes from its fields with the engine's `record_hash`) and
`linked` (its `prev_hash` is the previous entry's hash, or the genesis hash for entry 1).
404 for a sequence number not in the log.

**`POST /api/audit/verify`** (CSRF like every state change): re-checks every hash with
`auditlog.verify_chain` and answers

```json
{"chain_ok": true, "broken_at": null, "entries": 57, "last_seq": 57, "last_hash": "...",
 "verified_at": "...", "verified_by": "viewer1", "seq": 58}
```

`broken_at` is the first sequence number that does not fit. The verification itself is
written to the log as `AUDIT_CHAIN_VERIFIED` (no fund) with `{"intact", "broken_at",
"entries", "last_seq"}`, so the log shows who checked it and what they found; `seq` is
that entry.

**`GET /api/audit/export.csv`** (same filters): every matching entry in chain order
(oldest first) as CSV with the columns `seq, ts, actor, role, action, fund, case_id,
payload, prev_hash, hash`; `payload` is the stored JSON, so each row's hash recomputes
with the engine's `record_hash` and an unfiltered export re-verifies end to end. File
name `audit_{FUND or ALL}_{YYYY-MM-DD}.csv` (today, UTC). Audited as `EXPORT_DOWNLOADED`
(fund: the filter's fund, else none) with `{"export": "audit_csv", "filename", "bytes",
"sha256", "rows", "filters"}`, in the transaction that produces the file. More than
100,000 matching entries is refused with 422 (narrow the filters).

`daytrail.day_entries` keeps its behaviour; the window it finds is factored into
`day_window` so the `as_of` filter selects exactly the same entries.

### History across days

- **A case across days**: `GET /api/funds/{code}/cases/{case_id}` gains `days`, the case
  at the end of every day it was in a run (from `case_snapshots`), oldest first:
  `{"as_of", "day_status", "is_open", "status", "cause", "category", "age_days",
  "nav_impact", "nav_impact_bp", "material", "escalated", "sla_breached", "reviewed_by"}`.
  `cause` is the engine's current cause that day (`ledger.current_category`), `category`
  the rules' cause; `is_open` is false on the day it cleared.
- **The overview's trend** gains `open_gross_impact` per day (the same figure as MI's
  trend, now computed once in `mi.trend_rows`), so the overview shows the open impact per
  run day gross beside net, and each day in its figures opens that day.

### Front end

- **Audit log screen** (`/audit`, `g l`, "Audit log" in the screen list),
  `screens/audit/`: the header carries "Verify chain" and "Export CSV". Filters live in
  the address (`scope=all` for every fund and system entry, else the fund being worked;
  `only_day=1` for the business day being worked; `from`, `to`, `actor`, `action`,
  `case`; `before` for the page), so a filtered view can be shared. The table: entry,
  recorded, who, action, case (opening the case in the workbench) and one line of
  detail; each entry's payload and hashes, with the server's check of that entry, behind
  a disclosure. Older and newer pages, and the position ("51 to 100 of 1,234"). The
  verification's verdict in plain words; a broken chain names the entry and shows it.
- **Sign-off**: the audit trail gains a link to the day in the audit log.
- **Case workbench**: the case pane gains "Across days": first seen, and per day the
  status, cause, age, impact and flags, each day opening the case as it stood then.
- **Overview trend**: net and gross open impact per day in its figures, days as links.
- `api/queries.ts` gains `useAuditLog`, `useAuditFacets`, `useAuditEntry`,
  `useVerifyChain`, `useAuditExport` and their paths; the vocabulary gains
  `AUDIT_CHAIN_VERIFIED`, `USER_CREATED`, `FUND_CREATED`, `ACCOUNT_LOCKED` and the
  audit export.

### Tests

- pytest `tests/web/test_auditviewer.py`: sign-in needed and every role may read, verify
  and export; each filter alone and combined (fund, system entries, `as_of` equal to the
  day trail, dates and instants, actor, action list, case), bad filters 422; keyset pages
  covering every entry once with `newer` and both cursors; one entry with `hash_ok` and
  `linked`, and a tampered one; verify intact, broken (the first broken seq), audited and
  CSRF-protected; the CSV's columns, rows re-hashing with the engine's `record_hash`, an
  unfiltered export re-verifying end to end, the export audited with its hash and the
  row cap. `tests/web/test_cases.py` gains the case across days (open, carried, cleared);
  `tests/web/test_overview.py` the trend's gross figure across days.
- Vitest `screens/audit/AuditScreen.test.tsx` (filters to the query and the address,
  paging, the entry detail, verification intact and broken, export and its refusal), the
  case pane's days and the overview trend's figures.
- Playwright `e2e/audit.spec.ts`: a viewer filters the log to a case's decisions, opens
  an entry, verifies the chain and exports the CSV (file name and header); an analyst
  sees a carried case across days; axe on the audit screen in both themes.
