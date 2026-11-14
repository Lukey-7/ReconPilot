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
