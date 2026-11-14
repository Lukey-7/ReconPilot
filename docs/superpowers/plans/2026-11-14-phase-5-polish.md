# Phase 5: Polish Implementation Plan

**Goal:** The finish a desk notices: a command palette and the full shortcut set, motion
that explains change, an uncluttered screen for each job, then accessibility, admin pages,
the AI per-fund switch, unlocking, hardening and performance with a year of history.

**Spec:** `docs/superpowers/specs/2026-11-13-reconpilot-web-app-design.md` (section 10,
"Screens and look", and phase 5 of section 14). Phases 1 to 4 are the base; their route,
field and component names are not changed here.

**Stages:** 5a feel and motion (this section). Later stages add their own sections below.

## Global constraints

The phase 2 and 3 constraints stand: live data only, one vocabulary
(`web/src/vocabulary.ts`), status never by colour alone, controls enforced on the server,
shortcuts never while typing, all motion off under `prefers-reduced-motion`. Night desk's
palette (slate, blue accent, orange-amber for "needs you") is kept. Before every commit:
`pytest -q` at the root, and `npm run typecheck`, `npm run lint`,
`npm test -- --run --no-file-parallelism` in `web/`. Playwright runs with `--workers=1`
and Chromium only.

---

## Stage 5a: feel and motion

Front end only; no API change.

### Keyboard framework (`keyboard/KeyboardProvider.tsx`)

- `useShortcut(keys, handler, options)` keeps its signature and gains two options:
  `palette` (`true` or a label: the shortcut is also an action in the command palette,
  under its group) and `whileTyping` (the shortcut fires even with focus in a field; only
  `mod+k` uses it).
- `useCommand(label, run, {group, enabled, keywords, keys})` registers an action that has
  no key of its own, for the palette only. `useCommands()` lists every registered action
  (shortcuts marked `palette` and commands), in registration order. An action is
  registered only while the person may run it (`enabled`), so the palette never offers
  what the role or the day's state forbids; the server still checks every request.
- Esc in a text field (outside a dialog) leaves the field, so the screen's keys work
  again; inside a dialog or menu Esc stays the dialog's.

### The full shortcut set (spec section 10)

`g` then `o`/`u`/`q`/`s`/`m`/`l` (and `g f` for funds), `j`/`k` and the arrows, `Enter`,
`a`, `r`, `c`, `/` (the workbench's search; the audit log's case filter), `?` (the
shortcuts dialog), `Esc`, and `Ctrl+K` (or Cmd+K) for the palette. The help dialog lists
whatever is registered on the screen in view, including the palette and Esc.

### Command palette (`shell/CommandPalette.tsx`)

A dialog opened by `Ctrl+K` or the top bar's search button: one field (a combobox) over
one list, grouped:

- **Actions**: every registered action the person may run now: theme, shortcuts, sign out,
  the demo's "Work as"; on the workbench approve, reject, reclassify and search; on upload
  run the day; on sign-off "Sign off the NAV…" (opens the same confirmation as the
  button, never signs off directly); on MI the two exports; on the audit log verify chain
  and export CSV.
- **Screens**: the six screens and Funds.
- **Cases**: the day's cases from the queue's own query (`GET .../cases`), matched on
  case id, security, cause and status; each opens the case in the workbench.
- **Funds** and **Business days**: switch the fund or the day, staying on the screen.

Typing narrows every group (every word must match); arrows move, Enter runs, Esc closes.
The action runs after the dialog closes, so focus lands where the action puts it.

### Motion (`motion.ts`, CSS)

- `useTween(value, {duration})`: figures ease from their old value to the new over about
  200 ms (the strip's NAV and NAV per share, the overview's gross and net impact); the
  new value at once under reduced motion or on first show.
- The release status: when it changes (Blocked to Ready, Ready to Signed off) the
  strip's lamp and the overview's status pulse once.
- List entry: the queue's and the overview's rows fade in on first show (staggered by a
  few ms per row, at most ten); panes swap in 150 to 200 ms.
- Every animation and transition is off under `prefers-reduced-motion` (tokens set to 0,
  `useTween` returns the target).

### Uncluttering pass (owner's feedback)

One job per screen, the most important thing first, detail on demand, fewer panels, no
decorative statistics:

- **Top bar**: screen links without key hints (the shortcut is in the tooltip, the help
  dialog and the palette); one search button for the palette; shortcuts as an icon.
- **Overview**: five panels instead of seven, in two columns that stack without gaps:
  release status, open breaks and, in one quiet panel, the trend with what cleared today
  on the left; the day's account and, in one panel, ageing with SLA breaches and
  escalations on the right. Each section keeps its own heading and region. The impact
  totals are gross, net and material (gross exposure is each case's own figure, in the
  workbench); no legend; ageing without its bars.
- **Workbench**: the evidence pane no longer repeats the case's NAV impact (the case
  pane's headline); the FX rate it was converted at stays under the breaks.
- **Upload**: once the day has run, the file list folds behind one line.
- **Sign-off, MI, audit log, funds**: looked at and left as they are: each already leads
  with its one job (the conditions and the action; the matrix and exports; the log and its
  check; the funds and settings). Only the audit log's two demo actions gain their words.

### Tests

- Vitest `keyboard/KeyboardProvider.test.tsx`: `palette` and `useCommand` entries listed
  and run, disabled ones absent, `whileTyping`, Esc leaving a field.
- Vitest `shell/CommandPalette.test.tsx`: Ctrl+K opens it (also from a field), jump to a
  screen, a case, a fund and a day, keyboard navigation, filtering, role-gated actions
  (an analyst is offered approve, a viewer is not; an approver who may sign off is
  offered sign-off, which opens the confirmation), Esc closes.
- Vitest `motion.test.tsx`: `useTween` eases, and returns the target under reduced motion.
- Existing tests keep passing; the Playwright journeys run once at the end.
