# Phase 1: Backend Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working backend in which a signed-in user uploads a fund's day of files, validates and runs them through the unchanged engine, reviews the cases and signs off the NAV, with every control and audit entry held in PostgreSQL, plus the four engine fixes the design requires.

**Architecture:** A new package `src/reconpilot_web/` wraps the engine (`src/reconpilot/`), which it calls as a library and never modifies in behaviour. FastAPI serves `/api`; a worker process claims jobs from a PostgreSQL table and runs `pipeline.run_day`; everything persists to PostgreSQL through SQLAlchemy 2 with Alembic migrations. Development and tests use an embedded PostgreSQL started from Python (`pgserver`).

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.1, Alembic, psycopg 3, pgserver, argon2-cffi, python-multipart, httpx and pytest for tests.

**Spec:** `docs/superpowers/specs/2026-11-13-reconpilot-web-app-design.md` (sections 3, 6, 7, 8, 9, 12, 13 and phase 1 of section 14).

## Global Constraints

- The engine's behaviour is unchanged for the command line: all 95 existing tests pass after every task.
- The engine never imports `reconpilot_web`.
- No Docker. Everything runs natively; tests start PostgreSQL through `pgserver`.
- Python `>=3.10` stays the floor in `pyproject.toml`; web dependencies go in an optional extra `web` (and test tools in `dev`).
- No AI attribution in commits, PR text or docs.
- Provider API keys only from environment variables, never stored in the database or sent to the browser.
- Passwords: argon2id, minimum 12 characters, rejected if in the common-password list.
- Session cookie `rp_session`: httpOnly, SameSite=Lax, Secure when `RP_COOKIE_SECURE=1`; idle timeout 30 minutes, absolute 12 hours.
- CSRF: cookie `rp_csrf` plus header `X-CSRF-Token` must match on every POST, PUT, PATCH and DELETE.
- Lockout: 5 consecutive failed sign-ins lock the account for 15 minutes.
- Release reasons and cause names in API responses use the engine's enum values (`MISSING_TRADE`, `TIMING`, ...); human wording is the front end's job (phase 2).
- Defaults for fund settings are the engine's: materiality 1.0 bp, escalate after 5 days, SLA 2 days material and 5 days other.

## Review Focus

1. Two analysts decide the same case at once: the second request is refused with HTTP 409 and the first decision stands (Task 11).
2. A file exported from Excel arrives with a UTF-8 byte-order mark and CRLF line endings: it validates and runs like any other file (Task 8).
3. The worker dies or the engine raises mid-run: nothing from that run is persisted, the job is retried up to 3 times, then the day is marked `failed` with the error (Tasks 9 and 10).
4. A signed-out session cookie is replayed: every route answers 401 (Task 6).
5. Many requests append audit entries concurrently: the chain stays intact and `seq` has no gaps (Task 5).

---

## File Structure

```
src/reconpilot/                     engine (small, behaviour-preserving changes in Tasks 1-2)
  ai.py                             evidence: carried trades, whole-number quantities
  ledger.py                         recompute disagreement flag after carrying a diagnosis
  matching.py                       CarriedItem.trade; carry_forward(result, day)
  pipeline.py                       run_day(check_settings=...)
  storage.py                        case_to_dict / case_from_dict, open-item trades
  audit.py                          public record_hash()
src/reconpilot_web/
  __init__.py
  config.py                         Settings from environment
  devdb.py                          embedded PostgreSQL for dev and tests
  db.py                             engine, session factory, Base
  models.py                         SQLAlchemy tables
  migrations/                       Alembic env + versions
  auditlog.py                       DbAuditLog (engine-compatible)
  security.py                       passwords, tokens, CSRF
  auth.py                           sessions, current user, role dependencies, routes
  funds.py                          fund creation, calendar, previous business day, routes
  validation.py                     file validation report
  days.py                           upload route, day status
  jobs.py                           queue: enqueue, claim, complete, fail
  runner.py                         build DayData, run the engine, persist
  cases.py                          case queue, detail, decisions
  release.py                        release status, sign-off, locking
  app.py                            FastAPI app factory
  cli.py                            reconpilot-web: dev, serve, worker, migrate, create-user, create-fund
  common_passwords.txt
tests/web/
  conftest.py                       database, app client, users, fund, sample files
  test_*.py                         one per module
```

---

### Task 1: AI fixes for carried cases and number formatting

**Files:**
- Modify: `src/reconpilot/models.py` (`CarriedItem` gains `trade: Trade | None = None`)
- Modify: `src/reconpilot/matching.py` (`carry_forward`)
- Modify: `src/reconpilot/ai.py` (`build_evidence`)
- Modify: `src/reconpilot/ledger.py` (`roll_forward`, the diagnosis carry-over block)
- Modify: `src/reconpilot/storage.py` and `src/reconpilot/ledger.py` (`save_open_items` / `load_open_items` round-trip the trade)
- Modify: `src/reconpilot/cli.py`, `src/reconpilot/evaluate.py` (pass `day` to `carry_forward`)
- Test: `tests/test_ai_carried.py`

**Interfaces:**
- Produces: `carry_forward(result: ReconResult, day: DayData | None = None) -> tuple[list[CarriedItem], list[CashLine]]`. When `day` is given, each carried book item's `trade` is the `Trade` from `day.book_trades` or from `day.carried_book_items[*].trade` with the same reference, else `None`.
- Produces: `build_evidence` lists carried items' trades under `book_trades` (deduplicated by `trade_id`), and renders every whole-valued quantity as an `int` (`25900.0` → `25900`) in `book_position`, `custodian_holding`, `breaks` (for `QUANTITY` breaks) and `book_trades`.
- Produces: in `roll_forward`, after a carried case keeps an earlier diagnosis, `t.ai_flag = DISAGREEMENT_FLAG if t.ai_status == "ACCEPTED" and t.ai_category is not t.category else ""`.

- [ ] **Step 1: Write the failing tests**

```python
def test_carried_fx_case_evidence_includes_original_trade():
    # day 1: EUR trade T1 settles 1% off -> CASH_AMOUNT break; day 2: carried pair, no trades
    ev = build_evidence(day2, result2.recon, result2.open_cases[0])
    assert [t["trade_id"] for t in ev["book_trades"]] == ["T1"]

def test_whole_quantities_are_integers_in_evidence():
    ev = build_evidence(day, recon, case)   # position 25,900 units
    assert ev["book_position"]["quantity"] == 25900 and isinstance(ev["book_position"]["quantity"], int)

def test_disagreement_flag_recomputed_after_carried_diagnosis():
    # fake client answers UNKNOWN on day 2; rules carry FX_DIFFERENCE from day 1
    case = result2.open_cases[0]
    assert case.category is Category.FX_DIFFERENCE and case.ai_category is Category.UNKNOWN
    assert case.ai_flag == DISAGREEMENT_FLAG

def test_open_items_round_trip_keeps_trade(tmp_path): ...
    # save_open_items then load_open_items: CarriedItem.trade equals the original Trade
```

Use the `FakeClient` pattern from `tests/test_ai.py` and `make_day`/`trade`/`cash` from `tests/conftest.py`.

- [ ] **Step 2: Run to confirm they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ai_carried.py -q`
Expected: 4 failures.

- [ ] **Step 3: Implement the four changes listed under Interfaces.** Update the two `carry_forward` callers in `cli.py` (`_load_day` keeps loading from file; `save_open_items` gets the day) and `evaluate.py` (`carry_forward(prev.recon, prev.day)`).

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 99 passed (95 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/reconpilot tests/test_ai_carried.py
git commit -m "Give the AI the original trade for carried cases and flag carried disagreements"
```

### Task 2: Engine interfaces the web layer needs

**Files:**
- Modify: `src/reconpilot/pipeline.py`, `src/reconpilot/storage.py`, `src/reconpilot/audit.py`
- Test: `tests/test_engine_interfaces.py`

**Interfaces:**
- Produces: `run_day(..., check_settings: dict | None = None)`; the dict's keys are passed as keyword arguments to `nav.run_checks` (allowed: `max_price_age_days`, `movement_threshold`, `cash_tolerance`, `price_move_limits`). `None` keeps today's defaults.
- Produces: `storage.case_to_dict(case: Case) -> dict` and `storage.case_from_dict(d: dict) -> Case` (JSON-safe; enums as values). `save_cases`/`load_cases` use them.
- Produces: `audit.record_hash(record: dict) -> str` (the existing digest, made public; `_digest` stays as an alias).

- [ ] **Step 1: Failing tests:** `test_check_settings_change_price_move_limit` (a 3% equity move warns with `{"price_move_limits": {"EQUITY": 0.02, "BOND": 0.02}}` and passes without), `test_case_dict_round_trip` (every field of a fully populated `Case`, including `ai_category` and `resolved_category`, survives), `test_record_hash_matches_audit_log` (the hash of an appended entry minus its `hash` field equals `record_hash`).
- [ ] **Step 2:** Run `pytest tests/test_engine_interfaces.py -q`; expect 3 failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; expect 102 passed.
- [ ] **Step 5:** Commit `"Expose check settings, case serialisers and the audit hash for the web layer"`.

### Task 3: Web package, configuration and embedded database

**Files:**
- Modify: `pyproject.toml` (extra `web`: fastapi, uvicorn[standard], sqlalchemy>=2.0, alembic, psycopg[binary], pgserver, argon2-cffi, python-multipart; `dev` adds httpx; script `reconpilot-web = "reconpilot_web.cli:main"`; wheel packages both packages), `.gitignore` (`.rp_data/`)
- Create: `src/reconpilot_web/__init__.py`, `config.py`, `devdb.py`, `db.py`, `cli.py` (skeleton), `tests/web/conftest.py`, `tests/web/test_config.py`

**Interfaces:**
- Produces: `Settings` dataclass with `database_url: str`, `migration_database_url: str`, `mode: Literal["real","demo"]`, `cookie_secure: bool`, `data_dir: Path`, `ai_cache_dir: Path`; `load_settings(env: Mapping[str,str] = os.environ) -> Settings`. Variables: `RP_DATABASE_URL`, `RP_MIGRATION_DATABASE_URL` (defaults to `RP_DATABASE_URL`), `RP_MODE` (default `real`), `RP_COOKIE_SECURE`, `RP_DATA_DIR` (default `.rp_data`).
- Produces: `devdb.start(data_dir: Path) -> str` returns a superuser URI for an embedded server in `data_dir/pg`, reusing it if running.
- Produces: `db.make_engine(url: str) -> Engine`, `db.SessionLocal` factory via `db.configure(url)`, `db.Base` (DeclarativeBase).
- Produces (tests): fixtures `pg_uri` (session-scoped embedded server in a temp dir), `db_session`, `settings`.

- [ ] **Step 1:** Failing tests: `test_load_settings_defaults`, `test_load_settings_rejects_unknown_mode` (raises `ValueError` for `RP_MODE=prod`), `test_devdb_starts_and_answers` (`select 1` returns 1).
- [ ] **Step 2:** Run `pytest tests/web -q`; expect failures.
- [ ] **Step 3:** Install `uv pip install -e ".[dev,web]"`, implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add the web package skeleton with configuration and an embedded PostgreSQL"`.

### Task 4: Schema, migrations and instance mode

**Files:**
- Create: `src/reconpilot_web/models.py`, `src/reconpilot_web/migrations/` (Alembic `env.py`, `script.py.mako`, `versions/0001_initial.py`), `alembic.ini` at project root, `tests/web/test_schema.py`
- Modify: `src/reconpilot_web/cli.py` (`migrate` command), `tests/web/conftest.py` (migrate once per session; truncate all tables except `instance_settings` between tests)

**Interfaces:**
- Produces tables exactly as spec section 6, with these keys: `cases` primary key `(fund_id, case_id)` and an integer `version` column; `case_snapshots` primary key `(fund_id, case_id, as_of)`; `audit_log.seq` bigint unique; `business_days` unique `(fund_id, as_of)`; `jobs.status` in `queued|running|done|failed`, `attempts` int, `max_attempts` int default 3.
- Produces: migration creates role `rp_app` if missing (password from `RP_APP_DB_PASSWORD`, default `rp_app_dev` in dev only), grants SELECT/INSERT/UPDATE/DELETE on all tables to it **except** `audit_log`, where it grants SELECT and INSERT only; a trigger `audit_log_append_only` raises an exception on UPDATE, DELETE and TRUNCATE.
- Produces: `cli migrate` writes `instance_settings(mode)` once; `models.assert_instance_mode(session, expected: str) -> None` raises `RuntimeError("database is a <mode> database; this instance runs in <expected> mode")` on mismatch.

- [ ] **Step 1:** Failing tests: `test_all_tables_exist`, `test_app_role_cannot_update_audit_log` (connect as `rp_app`; UPDATE and DELETE raise `psycopg.errors.InsufficientPrivilege` or the trigger's exception), `test_superuser_cannot_update_audit_log_either` (trigger fires), `test_instance_mode_mismatch_refused`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add the database schema with an append-only audit log and instance mode guard"`.

### Task 5: Database audit log

**Files:**
- Create: `src/reconpilot_web/auditlog.py`, `tests/web/test_auditlog.py`

**Interfaces:**
- Consumes: `audit.record_hash` (Task 2), `models.AuditEntry`.
- Produces: `DbAuditLog(session: Session, fund_id: int | None = None)` with `append(actor: str, role: str, action: str, payload: dict | None = None) -> dict` (same record fields and hash as the engine's `AuditLog`; serialised with `pg_advisory_xact_lock(727274)`; writes in the caller's transaction), `entries(fund_id: int | None = None) -> list[dict]`, and module function `verify_chain(session) -> tuple[bool, int | None]`.

- [ ] **Step 1:** Failing tests: `test_append_matches_engine_format` (same keys and a hash equal to `record_hash`), `test_chain_verifies`, `test_tamper_detected_via_superuser_bypass` (disable the trigger as superuser, edit a payload, re-enable: `verify_chain` returns `(False, seq)`), `test_concurrent_appends_keep_chain` (20 threads × 10 appends, each in its own session: 200 entries, `seq` 1..200, chain verifies), `test_rollback_discards_entry`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Write the hash-chained audit log to PostgreSQL"`.

### Task 6: Accounts, sessions and roles

**Files:**
- Create: `src/reconpilot_web/security.py`, `auth.py`, `app.py`, `common_passwords.txt` (the 10,000 most common passwords from a public list, one per line), `tests/web/test_auth.py`
- Modify: `cli.py` (`create-user --username --role --admin --display-name`, reading the password from a prompt or `RP_NEW_PASSWORD`)

**Interfaces:**
- Produces: `hash_password(pw: str) -> str`, `verify_password(hash: str, pw: str) -> bool`, `check_password_policy(pw: str) -> list[str]` (problems; empty means acceptable), `new_token() -> str` (32 random bytes, urlsafe), `token_digest(token: str) -> str` (sha256 hex).
- Produces routes: `POST /api/auth/login {username, password}` → 200 with `{user}` and sets `rp_session` and `rp_csrf`; 401 on bad credentials; 423 when locked. `POST /api/auth/logout` → 204, revokes the session. `GET /api/auth/me` → `{username, display_name, role, is_admin}`.
- Produces dependencies: `current_user` (401 if missing, expired, revoked or inactive), `require_roles(*roles: str)` (403 otherwise), `require_admin`, `csrf_protect` (403 on mismatch; applied to every non-GET route).
- Produces: `create_app(settings: Settings) -> FastAPI`; security headers on every response: `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.
- Audit actions: `SIGN_IN`, `SIGN_IN_FAILED`, `ACCOUNT_LOCKED`, `SIGN_OUT`, `USER_CREATED`.

- [ ] **Step 1:** Failing tests: `test_login_sets_cookies_and_me_works`, `test_wrong_password_401_and_audited`, `test_lockout_after_five_failures` (sixth attempt with the right password → 423), `test_logout_then_cookie_replay_401` (Review Focus 4), `test_post_without_csrf_403`, `test_idle_timeout_expires_session` (move `last_seen_at` back 31 minutes → 401), `test_password_policy` (`"short"` and `"password1234"` rejected; a 16-character random string accepted), `test_security_headers_present`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add built-in accounts with server-side sessions, CSRF protection and lockout"`.

### Task 7: Funds and the business calendar

**Files:**
- Create: `src/reconpilot_web/funds.py`, `tests/web/test_funds.py`
- Modify: `cli.py` (`create-fund --code --name --start-date [--base-currency USD]`)

**Interfaces:**
- Produces: `DEFAULT_FUND_SETTINGS` (materiality_bp 1.0, escalate_after_days 5, sla_days_material 2, sla_days_other 5, ai_enabled False, check_settings {}), `fund_lifecycle(fund) -> LifecycleSettings`, `fund_check_settings(fund) -> dict`, `previous_business_day(fund, d: date) -> date | None` (previous weekday not in `fund.non_business_dates`; `None` when `d == fund.start_date`), `is_business_day(fund, d) -> bool`.
- Produces routes: `GET /api/funds` → list of `{code, name, base_currency, start_date, latest_day, latest_status}`; `GET /api/funds/{code}` → the fund with settings.
- Audit: `FUND_CREATED`.

- [ ] **Step 1:** Failing tests: `test_previous_business_day_skips_weekend_and_holidays` (Monday 2026-11-16 with Friday 2026-11-13 a holiday → Thursday 2026-11-12), `test_start_date_has_no_previous_day`, `test_list_funds_requires_sign_in`, `test_viewer_can_list_funds`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add funds with per-fund settings and a business calendar"`.

### Task 8: Upload and validation

**Files:**
- Create: `src/reconpilot_web/validation.py`, `src/reconpilot_web/days.py`, `tests/web/test_validation.py`, `tests/web/test_upload.py`
- Test data: generate with `reconpilot.sequence.generate_sequence` + `storage.write_day` inside fixtures (no committed files).

**Interfaces:**
- Produces: `FILE_KINDS` mapping each `storage.FILES` key except `truth` to its filename; `REQUIRED` = securities, fx, trades, positions, holdings, cash, fund.
- Produces: `validate_files(files: dict[str, bytes], as_of: date) -> ValidationReport` with `errors: list[Issue]`, `warnings: list[Issue]`, `Issue(file: str, row: int | None, message: str)`. Checks (spec 7.2): required files present; exact headers; values parse (dates ISO, numbers finite); `fund.csv` as_of equals `as_of`; trade, position, holding and cash security ids (non-blank) exist in `securities.csv`; no duplicate `trade_id` or `entry_id`; `settle_date >= trade_date`; every currency has an FX rate; per-file limit 5 MB and 200,000 rows. Missing optional files are warnings. Decodes UTF-8 with or without BOM; accepts CRLF.
- Produces route: `POST /api/funds/{code}/days/{as_of}/files` (analyst or approver; multipart, field `files`, filenames mapped to kinds by name) → `{status, errors, warnings}`; stores bytes and sha256 in `input_files`, replacing earlier files of the same kind for that day; sets day status `validated` or `uploaded` (with errors). Refused with 409 when the day is signed off, or when the previous business day exists and is not signed off ("Sign off 2026-11-12 first."), or when `as_of` is before the fund's start date or not a business day. `GET /api/funds/{code}/days/{as_of}` → day status, files, last validation, NAV and release when ready.
- Audit: `FILES_UPLOADED` (filenames, kinds, hashes), `VALIDATION_FAILED` or `VALIDATION_PASSED`.

- [ ] **Step 1:** Failing tests: `test_valid_day_passes`, `test_missing_required_file`, `test_wrong_header`, `test_as_of_mismatch`, `test_unknown_security`, `test_duplicate_trade_id`, `test_settle_before_trade`, `test_bom_and_crlf_accepted` (Review Focus 2), `test_upload_refused_until_previous_day_signed_off`, `test_viewer_cannot_upload` (403).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Validate uploaded day files before any run"`.

### Task 9: Job queue and worker

**Files:**
- Create: `src/reconpilot_web/jobs.py`, `tests/web/test_jobs.py`
- Modify: `cli.py` (`worker [--once]`)

**Interfaces:**
- Produces: `enqueue(session, kind: str, payload: dict, created_by: int | None) -> int`, `claim(session, worker_id: str) -> Job | None` (`FOR UPDATE SKIP LOCKED`, oldest `queued` with `run_after <= now`), `complete(session, job_id, result: dict)`, `fail(session, job_id, error: str)` (status back to `queued` with `run_after = now + 10s * attempts` until `attempts == max_attempts`, then `failed`), `run_worker(settings, once: bool = False, handlers: dict[str, Callable] | None = None)`.
- Produces: handler registry `HANDLERS: dict[str, Callable[[Session, dict], dict]]`; each handler receives an open session (the worker commits on success and rolls back on exception, then calls `fail` in a fresh transaction) and the job payload, and returns the result dict. Task 10 registers `"run_day": runner.run_day_job`.

- [ ] **Step 1:** Failing tests: `test_two_workers_never_claim_the_same_job` (two threads, 50 jobs, each claimed once), `test_failure_retries_then_fails` (handler raises; after 3 attempts status `failed` and `error` recorded) (Review Focus 3), `test_complete_records_result`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add a PostgreSQL job queue and worker"`.

### Task 10: Running a day through the engine

**Files:**
- Create: `src/reconpilot_web/runner.py`, `src/reconpilot_web/aicache.py`, `tests/web/test_runner.py`
- Modify: `days.py` (`POST /api/funds/{code}/days/{as_of}/run` → 202 `{job_id}`; `GET /api/jobs/{id}` → status)

**Interfaces:**
- Consumes: `pipeline.run_day` with `check_settings` (Task 2), `carry_forward(result, day)` (Task 1), `storage.read_day`, `storage.case_to_dict/case_from_dict`, `DbAuditLog`, `fund_lifecycle`, `fund_check_settings`, `previous_business_day`.
- Produces: `DbResponseCache(session)` with the engine cache's `get(key) -> str | None` and `put(key, provider, model, response)`.
- Produces: `run_day_job(session, payload: {"business_day_id": int, "user_id": int}) -> dict` which, in **one transaction**: writes the day's files to a temp folder and `read_day`s it; attaches the previous business day's `open_items` (book items with their trades) and its open cases from `case_snapshots`; calls `run_day` with the fund's lifecycle and check settings, `DbAuditLog`, and the AI client only if `fund.settings.ai_enabled` and a key is configured; then upserts `cases` (bumping `version`), replaces the day's `case_snapshots`, `breaks` and `open_items`, stores NAV, checks and the run summary on `business_days`, sets status `ready`. Any exception rolls everything back; the job's failure path sets the day `failed` with the message after the last attempt.
- Produces re-run behaviour (spec 7.5): allowed only for the fund's latest day and only if not signed off; decisions on that day whose case still exists with the same `category` are re-applied through `ReviewSession` as the original user; others get `DECISION_VOIDED_BY_RERUN`; cases from the earlier run that no longer exist get `CASE_WITHDRAWN_BY_RERUN`.
- Audit: the engine's own entries (`AI_CALL`, `CASE_ESCALATED`, ...), plus `RUN_STARTED`, `RUN_FINISHED`, `RUN_FAILED`.

- [ ] **Step 1:** Failing tests: `test_run_creates_cases_and_snapshots`, `test_second_day_carries_cases_and_items` (a late settlement on day 1 clears on day 2 with `resolved_category == TIMING`), `test_engine_error_rolls_back_everything` (monkeypatch `run_day` to raise: no cases, no snapshots, no `RUN_FINISHED`), `test_rerun_reapplies_matching_decisions_and_voids_others`, `test_rerun_refused_after_sign_off`, `test_ai_off_by_default_makes_no_calls` (a key is set; no `AI_CALL` entries).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Run uploaded days through the engine and persist the results"`.

### Task 11: Case queue, detail and decisions

**Files:**
- Create: `src/reconpilot_web/cases.py`, `tests/web/test_cases.py`

**Interfaces:**
- Consumes: `review.ReviewSession`, `DbAuditLog`, `storage.case_from_dict`.
- Produces routes (all signed-in roles may read):
  - `GET /api/funds/{code}/days/{as_of}/cases?status=&category=&material=&escalated=&sla=&age=&ai_disagrees=&q=` → open cases for that day sorted by `-abs(nav_impact)`, each with `case_id, security_id, security_name, category, ai_category, ai_flag, status, final_category, nav_impact, nav_impact_bp, gross_exposure, material, escalated, sla_breached, age_days, age_bucket, version`.
  - `GET /api/funds/{code}/cases/{case_id}?as_of=` → the full case plus `breaks`, `book_position`, `custodian_holding`, related `book_trades` and custodian cash lines (from stored files), and `history` (decisions and audit entries for the case, oldest first).
  - `POST /api/funds/{code}/cases/{case_id}/decision {decision: "approve"|"reject"|"reclassify", category?, note?, version}` (analyst or approver; CSRF) → the updated case. 409 when `version` is stale (Review Focus 1), when the day is signed off, or when the case is cleared; 422 when reject has no note or reclassify has no valid category. Records a `decisions` row and the engine's `CASE_*` audit entry in one transaction.

- [ ] **Step 1:** Failing tests: `test_queue_sorted_by_absolute_impact`, `test_filters`, `test_detail_has_evidence_and_history`, `test_viewer_cannot_decide`, `test_reject_needs_note`, `test_stale_version_409` (two clients load version 1; the second decision gets 409 and the first stands), `test_decision_after_sign_off_409`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add the case queue, case detail and decisions API"`.

### Task 12: Release status, sign-off and day locking

**Files:**
- Create: `src/reconpilot_web/release.py`, `tests/web/test_release.py`

**Interfaces:**
- Produces: `ReleaseStatus(ready: bool, reasons: list[Reason])`, `Reason(code: str, message: str, case_ids: list[str])` with codes `PENDING_DECISIONS`, `MATERIAL_NOT_APPROVED`, `ESCALATED_NEEDS_APPROVER`, `CHECK_FAILED`, `NOT_RUN`. `compute_release(day_row, cases: list[Case], checks: list[dict]) -> ReleaseStatus`. Failed checks are those with status `FAIL` other than the engine's `NAV release`, which is reported to clients renamed `Material cases approved`.
- Produces: `can_sign_off(status, cases, user) -> list[Reason]` adds `FOUR_EYES` when the user decided any open case for the day.
- Produces routes: `GET /api/funds/{code}/days/{as_of}/release?for_user=me` → `{ready, reasons, signable_by_me, blocking_for_me}`; `POST /api/funds/{code}/days/{as_of}/signoff` (approver; CSRF) → 200 with the signed-off day, or 409 with reasons. Sign-off re-checks everything inside the transaction (`SELECT ... FOR UPDATE` on the day), calls `ReviewSession.sign_off`, sets status `signed_off`, `signed_off_by`, `signed_off_at`. Audit: `DAY_SIGNED_OFF` or `SIGN_OFF_BLOCKED` (from the engine).

- [ ] **Step 1:** Failing tests: `test_ready_only_when_all_conditions_met`, `test_engine_nav_release_check_renamed`, `test_analyst_cannot_sign_off` (403), `test_four_eyes_blocks_deciding_approver`, `test_signoff_locks_day_and_unblocks_next_upload`, `test_release_status_identical_for_every_role` (only `signable_by_me` differs).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Compute one release status on the server and sign off with four-eyes"`.

### Task 13: Equivalence with the command line, and the AI acceptance check

**Files:**
- Create: `tests/web/test_equivalence.py`, `scripts/ai_carried_check.py`
- Modify: `docs/evaluation.md`, `README.md` (multi-day AI table)

**Interfaces:**
- Consumes: everything above; `reconpilot.cli.main` for the command-line side.

- [ ] **Step 1:** Write `test_web_matches_cli_over_five_days`: generate a 5-day hard sequence (seed 11, 4 breaks a day) with `storage.write_day`; run each day through `reconpilot run` into a run folder, approving every pending case as `priya` (analyst) and escalated ones as `ann` (approver) and signing off as `tom`; do the same through the API (upload, run with the worker's handler called inline, decide, sign off). Assert per day: identical open `case_id`s, `category`, `status`, `nav_impact`, `age_days`, `cleared_on`, `resolved_category`; identical NAV per share and check statuses; identical sequences of audit `action` values after removing web-only actions (`SIGN_IN*`, `FILES_UPLOADED`, `VALIDATION_*`, `RUN_*`, `USER_CREATED`, `FUND_CREATED`).
- [ ] **Step 2:** Run it; fix any divergence in the web layer (never by changing engine behaviour).
- [ ] **Step 3:** Write `scripts/ai_carried_check.py`: the 8-day hard run (seed 21, 6 breaks a day) with the configured provider, printing AI accuracy on new and carried cases and the count of unflagged disagreements, exactly as measured in the spec.
- [ ] **Step 4:** Run it with `OPENAI_API_KEY` set. Acceptance: carried-case accuracy at least the new-case accuracy, and 0 unflagged disagreements. If not met, return to Task 1.
- [ ] **Step 5:** Run `reconpilot evaluate --multi-day --hard --ai`; add the rules-versus-AI multi-day table to `docs/evaluation.md` and the README's Results section.
- [ ] **Step 6:** Run `pytest -q`; all pass. Commit `"Prove the web pipeline matches the command line and publish multi-day AI results"`.

### Task 14: One command to run it

**Files:**
- Modify: `src/reconpilot_web/cli.py`, `README.md` (section "Running the web application")
- Test: `tests/web/test_cli.py`

**Interfaces:**
- Produces: `reconpilot-web dev` (starts the embedded database in `RP_DATA_DIR`, runs migrations, creates a fund `DEMO1` and users `analyst1`, `approver1`, `approver2`, `viewer1` with printed one-time passwords if the database is empty, then runs Uvicorn on 127.0.0.1:8000 and the worker in-process on a background thread; Ctrl+C stops all), `reconpilot-web serve [--host --port]` (API only), `reconpilot-web worker`.

- [ ] **Step 1:** Failing test: `test_dev_bootstrap_creates_fund_and_users_once` (call the bootstrap function twice against the test database: one fund, four users).
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement; then manually run `reconpilot-web dev`, sign in with `httpx` against `/api/auth/login`, upload a generated day, run it, list cases, approve, sign off. Record the commands in the README.
- [ ] **Step 4:** Run `pytest -q`; all pass.
- [ ] **Step 5:** Commit `"Add reconpilot-web dev to start the whole backend with one command"`.
