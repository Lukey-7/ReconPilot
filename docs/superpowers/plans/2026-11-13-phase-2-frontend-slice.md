# Phase 2: Front-end Slice Implementation Plan

**Goal:** A person can work a whole business day in the browser: sign in, see the
morning overview, work the case queue with the decision bar, and sign off the
NAV, in the combined visual direction (Night desk palette and NAV strip, the
workbench for case work, the Ledger's overview and sign-off), with the keyboard
basics. Every figure comes from the API.

**Spec:** `docs/superpowers/specs/2026-11-13-reconpilot-web-app-design.md`
(sections 9, 10 and phase 2 of section 14). Phase 1's API is the base; its route
and field names are not changed here.

**Stack:** Vite, React 19, TypeScript (strict, `noUncheckedIndexedAccess`), React
Router 7, TanStack Query 5, TanStack Table 8, Radix UI primitives (dialog,
popover, dropdown menu, tooltip), CSS custom properties (no CSS framework),
self-hosted fonts from `@fontsource` (the API's CSP allows `'self'` only),
Vitest with Testing Library and jsdom, ESLint 9 (typescript-eslint, react-hooks,
jsx-a11y).

## Global constraints

- Live data only. No figure, case, name or date from the mockups or sample files
  appears in `web/src`. Test fixtures live only in `*.test.tsx` files and
  `web/src/test/`.
- One vocabulary: cause, status, release-reason, check and day-status wording
  comes from `web/src/vocabulary.ts` and nowhere else. The API keeps the
  engine's enum values (`MISSING_TRADE`, `PENDING`, ...).
- Status is never shown by colour alone: every status carries an icon and a word.
  Orange-amber (`--signal`) means "needs you" and nothing else.
- Numbers use tabular figures and are right-aligned in tables.
- Controls are enforced on the server; the browser only mirrors them (a button
  can be hidden for a viewer, but the server's 403 is what counts).
- Shortcuts never fire while focus is in an input, textarea, select or
  contenteditable element. All motion is off under `prefers-reduced-motion`.
- Before every commit: `pytest -q` at the root, and `npm run typecheck`,
  `npm run lint`, `npm test -- --run` in `web/`.

## File structure

```
web/
  index.html                  loads /theme-init.js (theme before first paint; no inline script, for the CSP)
  public/theme-init.js
  vite.config.ts              React plugin; /api proxied to 127.0.0.1:8000; Vitest (jsdom) config
  eslint.config.js
  tsconfig.json
  src/
    main.tsx                  mounts <App/>
    app/App.tsx               providers (Query, Theme, Auth, Keyboard, Tooltip) and the router
    api/client.ts             apiFetch, ApiError, csrfToken(), setUnauthorisedHandler()
    api/types.ts              response types for every route the front end calls
    api/queries.ts            query keys and hooks (useFunds, useDays, useDay, useRelease, useOverview, ...)
    auth/AuthContext.tsx      AuthProvider, useAuth (user, signIn, signOut)
    auth/RequireAuth.tsx      redirects to /signin, remembering where the user was going
    auth/SignInScreen.tsx
    shell/AppShell.tsx        top bar + sticky NAV strip + <Outlet/>; registers g o / g q / g s and ?
    shell/TopBar.tsx          brand, screen links, fund and day selectors, user and role, theme, shortcuts
    shell/NavStrip.tsx        NAV, NAV per share, movement, release status with reasons, sign-off entry
    shell/workspace.tsx       WorkspaceProvider, useWorkspace (fund and day from ?fund=&day=), useScreenHref
    shell/HelpDialog.tsx      the ? dialog, listing every registered shortcut
    keyboard/KeyboardProvider.tsx  useShortcut, sequences ("g o"), isTypingTarget
    theme/ThemeProvider.tsx   system / light / dark, persisted; ThemeToggle
    motion.ts                 usePrefersReducedMotion
    vocabulary.ts             causes, statuses, release reasons, checks, day statuses, roles, age buckets
    format.ts                 money, bp, signed percent, dates (en-GB)
    components/               Icon, StatusLabel, CauseLabel, CheckLabel, ReleaseBadge, Figure, Kbd,
                              DataTable (TanStack Table), Placeholder, QueryState
    screens/OverviewScreen.tsx, CasesScreen.tsx, SignOffScreen.tsx
    styles/tokens.css         Night desk tokens, dark first, light theme, reduced motion
    styles/base.css, shell.css, components.css
    test/setup.ts             jest-dom, matchMedia stub, cookie and storage reset
    test/mockApi.ts           fetch stub: route table of "METHOD /path" -> status and body
    test/render.tsx           renderApp(route, api) with every provider
```

## Shared components (built in 2a, reused by later stages)

| Component | Contract |
|---|---|
| `Icon name=` | 16px stroked glyphs: check, cross, warn, dot, ring, reclass, lock, clock, sun, moon, key, up, down, eye, sort. Always `aria-hidden`; meaning is carried by adjacent text. |
| `StatusLabel status=` | `PENDING` (signal fill, "needs you"), `APPROVED` (green, check), `REJECTED` (red, cross), `RECLASSIFIED` (neutral, arrows), `CLEARED` (green, ring). Icon plus word from the vocabulary. |
| `CauseLabel cause=` | The vocabulary word for an engine category; unknown values fall back to "Unexplained". |
| `CheckLabel status=` | `PASS`, `WARN`, `FAIL` with icon and word. |
| `ReleaseBadge release= signedOff=` | Ready (green, check), Blocked (signal, warn) or Signed off (lock). Used by the strip and by sign-off. |
| `Money value= signed?`, `Bp value=`, `Pct value=` | Tabular figures, en-GB grouping, explicit sign when `signed`. |
| `DataTable` | TanStack Table wrapper: semantic `<table>`, `<caption>`, sortable headers as buttons with `aria-sort`, numeric columns right-aligned (`meta.numeric`), row activation by click or Enter, optional selected row. |
| `QueryState` | Loading, error (message from `ApiError`) and empty states for a query, so screens stay uncluttered. |

## API contract per screen

All requests send credentials; every non-GET request sends `X-CSRF-Token` equal
to the `rp_csrf` cookie. A 401 on any request other than sign-in clears the
user and returns to `/signin`. Errors carry FastAPI's `detail`: a string, an
object `{message, reasons}` (409 at sign-off) or a list (422 validation).

| Screen | Calls |
|---|---|
| Sign-in | `POST /api/auth/login {username, password}` → `{user}`; 401 wrong details, 423 locked. `GET /api/auth/me` → `{username, display_name, role, is_admin}`. `POST /api/auth/logout` → 204. |
| Shell (every screen) | `GET /api/funds` → `[{code, name, base_currency, start_date, latest_day, latest_status}]`. `GET /api/funds/{code}/days` (new, below). |
| NAV strip (every screen) | `GET /api/funds/{code}/days/{as_of}` → `nav {nav, nav_per_share, prior_nav_per_share, detail.movement}`, `status`, `signed_off_by`, `signed_off_at` (404 when the day has no files). `GET /api/funds/{code}/days/{as_of}/release?for_user=me` → `{ready, reasons[{code, message, case_ids}], day_status, signed_off, checks, signable_by_me, blocking_for_me}`. |
| Overview | `GET /api/funds/{code}/days/{as_of}/overview` (new, below). |
| Case workbench | `GET /api/funds/{code}/days/{as_of}/cases?status=&category=&material=&escalated=&sla=&age=&ai_disagrees=&q=` → queue rows. `GET /api/funds/{code}/cases/{case_id}?as_of=` → detail with evidence and `history`. `POST /api/funds/{code}/cases/{case_id}/decision {decision, category?, note?, version}` → the updated case; 409 stale version, signed-off day or cleared case; 422 missing note or cause. |
| Sign-off | `GET .../release?for_user=me`; `GET .../overview` (cases with `status`, `reviewed_by`, `reviewed_role` for "who decided what"); `POST /api/funds/{code}/days/{as_of}/signoff` → the signed-off day, or 409 `{message, reasons}`. The day's audit trail: `GET /api/funds/{code}/days/{as_of}/audit` → `{entries: [{seq, ts, actor, role, action, case_id, payload}], chain_ok, broken_at}` (added by the sign-off stage). |

After a decision or sign-off the client invalidates the `day`, `release`,
`overview` and `cases` queries for that fund and day, so the strip and every
screen agree.

### New: `GET /api/funds/{code}/days`

Any signed-in role. Newest first.

```json
{
  "fund": "GEF1",
  "start_date": "2026-11-09",
  "latest_day": "2026-11-10",
  "next_day": null,
  "days": [
    {"as_of": "2026-11-10", "status": "ready", "nav_per_share": 101.23, "open_cases": 6,
     "run_at": "...", "signed_off_by": null, "signed_off_at": null}
  ]
}
```

`next_day` is the business day whose files can be loaded next: the start date
when nothing is loaded, the business day after the latest day once that is
signed off, otherwise `null`. `nav_per_share` and `open_cases` are `null` until
a day has run.

### New: `GET /api/funds/{code}/days/{as_of}/overview`

Any signed-in role; 404 when the day has no files. Cases are the queue row
fields plus `reviewed_by`, `reviewed_role`, `review_note`, `first_seen`,
`sla_days` and `escalation_reason` (the impact recorded at escalation; label it
"at escalation").

```json
{
  "fund": {"code": "GEF1", "name": "...", "base_currency": "USD", "materiality_bp": 1.0},
  "as_of": "2026-11-10", "day_status": "ready", "has_run": true,
  "run_at": "...", "run_by": "analyst1", "signed_off_by": null, "signed_off_at": null,
  "nav": {"nav": 0, "nav_per_share": 0, "prior_nav_per_share": 0, "movement": 0,
          "gross_assets": 0, "cash": 0, "liabilities": 0},
  "checks": [{"name": "...", "status": "PASS", "detail": "..."}],
  "release": {"ready": false, "reasons": [{"code": "PENDING_DECISIONS", "message": "...", "case_ids": []}]},
  "run": {"matches": 0, "breaks": 0, "new_cases": 0, "carried_cases": 0},
  "accounted": {"breaks_found": 0, "breaks_in_cases": 0, "breaks_not_in_case": 0, "open_cases": 0,
                "decided": 0, "approved": 0, "rejected": 0, "reclassified": 0, "pending": 0},
  "impact": {"cases": [], "net": 0, "gross": 0, "gross_exposure": 0, "material": 0},
  "ageing": [{"bucket": "0-1", "count": 0, "net": 0, "gross": 0}, {"bucket": "2-5"}, {"bucket": ">5"}],
  "sla_breaches": [], "escalations": [],
  "cleared_today": [{"case_id": "...", "security_id": "...", "security_name": "...", "category": "TIMING",
                     "resolved_category": "TIMING", "clear_reason": "...", "nav_impact": 0, "age_days": 0}],
  "trend": [{"as_of": "...", "open_cases": 0, "new_cases": 0, "cleared_cases": 0, "material_open": 0,
             "escalated_open": 0, "sla_breaches_open": 0, "aged_over_5": 0, "open_nav_impact": 0,
             "avg_days_to_resolve": null}]
}
```

- `release` and `checks` are exactly what `GET .../release` returns for the day
  (the same functions compute both).
- `impact.net` is the sum of the open cases' NAV impacts; `impact.gross` the sum
  of their absolute impacts (so offsetting breaks cannot hide); `gross_exposure`
  the size of the underlying items. Show gross and net together, never net alone.
- `accounted`: `breaks_found` is every break the day's run found;
  `breaks_in_cases + breaks_not_in_case = breaks_found`; `decided + pending =
  open_cases`; `decided = approved + rejected + reclassified`.
- `trend` covers the fund's run days up to `as_of` (at most 20), oldest first,
  computed with the engine's `mi.summarise_day` from the day ledgers.
- Before a run: `has_run` false, `release` gives `NOT_RUN`, `nav`, `run`,
  `accounted` and `impact` are `null`, the lists are empty, `ageing` has zero
  counts, and `trend` still shows the earlier days.

## Keyboard

Registered through `useShortcut({keys, description, group, handler, enabled})`.
2a provides `g o` (overview), `g q` (cases), `g s` (sign-off), `?` (help) and
`Esc` (close the top dialog or popover). Later stages register `j`/`k`/arrows,
`Enter`, `a`, `r`, `c`, `/` on the workbench; the help dialog lists whatever is
registered. A `g` sequence waits 1.5 s for its second key.

## Tasks

### Stage 2a: foundations (this commit series)

1. This plan.
2. Backend: `GET /api/funds/{code}/days` (in `days.py`) and the overview route
   (`overview.py`), with `tests/web/test_overview.py`: day listing and
   `next_day`, sign-in required, 404 for a day with no files, the not-run shape,
   every break accounted for (including after a decision), gross and net impact,
   ageing buckets summing to the open cases, release identical to the release
   route, SLA breaches and escalations, cleared today and the trend across two
   days, viewers may read.
3. Serving: `create_app(settings, web_dist=None)` serves a built front end
   (files, then `index.html` for any other non-API path, with the security
   headers); `reconpilot-web serve` passes `web/dist` when it exists;
   `reconpilot-web dev` also starts Vite (`npm run dev` in `web/`) when
   `web/node_modules` exists and stops it on exit. Tests in `tests/web/test_serve.py`.
4. `web/` scaffold, tokens and fonts, vocabulary, formatting, API client, query
   hooks. Tests: `api/client.test.ts`, `vocabulary.test.ts`, `format.test.ts`.
5. Auth context, `RequireAuth`, sign-in screen. Tests: `auth/SignInScreen.test.tsx`
   (success, wrong details, locked, redirect back, 401 later returns to sign-in).
6. Shell: workspace (fund and day in the URL), top bar, NAV strip, theme,
   keyboard framework and help dialog, placeholder screens. Tests:
   `shell/NavStrip.test.tsx`, `shell/AppShell.test.tsx` (selectors from the API,
   switching day updates the URL and the strip), `keyboard/KeyboardProvider.test.tsx`
   (g o, ignored while typing, ? opens help, Esc closes), `theme/ThemeProvider.test.tsx`.

### Stage 2b: morning overview

Build `OverviewScreen` from `GET .../overview`: release status with reasons first,
then "every break accounted for", open breaks by NAV impact (gross and net),
ageing, SLA breaches and escalations, cleared today and the trend; checks behind
an expander. Case ids link to `/cases?fund=&day=&case=`. Tests with `mockApi`
fixtures, including a not-run day and a clean day.

### Stage 2c: case workbench and decision bar

`CasesScreen`: queue (`DataTable`), filters and search kept in the URL, case
pane with book-versus-custodian evidence, rule suggestion beside the AI second
opinion, investigation steps, draft query with copy, decision history; decision
bar (approve, reject with note, reclassify with cause) sending the case's
`version` and showing 409s in plain words; `j`/`k`, `Enter`, `a`, `r`, `c`, `/`.
Viewers see no decision bar. Tests per decision path and per role.

### Stage 2d: sign-off

`SignOffScreen`: release conditions in plain words, who decided what, the day's
audit trail with chain verification (adds the audit route above, with pytest
tests), the sign-off action and its blocked states (four-eyes, analyst, viewer,
already signed off). Tests per blocked state and a successful sign-off that
updates the strip.

## Testing summary

- Python: every new route has pytest tests against the embedded PostgreSQL.
- Front end: Vitest and Testing Library for components, hooks and screens, with
  `fetch` stubbed by `mockApi`; queries never reach a network.
- Playwright journeys and axe checks are phase 5 (polish).
