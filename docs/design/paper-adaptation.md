# ReconPilot in Paper: how the design system applies to a desktop operations tool

`paper-design-system.md` (in this folder) is the source of truth for the look. It was written
for a phone app, so this note records where ReconPilot follows it exactly and the few places
it adapts it for a dense, keyboard-driven desktop tool. Where this note is silent, follow
`paper-design-system.md` to the letter.

This replaces the earlier "Night desk" palette (design spec section 10). Behaviour,
features, wording rules and accessibility requirements are unchanged.

## Follow exactly

- Every colour token in sections 2.1 to 2.3, the accent gradient in 2.4 and its rule of
  at most three gradient touches on screen. The page glow counts as ambient, not as a touch.
- Type (section 3): Barlow for all UI text **and figures**, with `tabular-nums` on every
  number; JetBrains Mono 10.5 px uppercase with 1 px letter-spacing for codes only: case
  ids (EX-20261113-003), trade and break refs, ISINs, fund codes, mono section labels.
  Sentence case everywhere. Figures never wrap.
- Self-host the fonts with `@fontsource/barlow` (400, 500, 600, 700) and
  `@fontsource/jetbrains-mono` (400, 500). Do not load Google Fonts: the CSP blocks
  third-party origins. Remove the Sofia Sans and Red Hat Mono packages.
- Icons (section 4): Lucide via `lucide-react`, one set only, stroke 1.8 for navigation and
  2 inline, same shape in every state. `components/Icon.tsx` becomes a thin wrapper over
  Lucide so call sites keep working.
- Shape, depth and spacing (section 5): card radius 20, lead card 24, hairlines 0.5 px
  `--line`, the card and lead-card shadows, the spacing scale.
- Components (section 6): lead card, figure tiles, lists as one card with hairline rows,
  records (label left, value right), status pills with dot **and word**, quiet export chips,
  segmented controls and filter chips, empty states, loading shimmer and the 3 px gradient
  progress line, the Undo toast.
- Motion (section 7) with every duration and easing as listed; `prefers-reduced-motion`
  turns all of it off.
- The do-and-don't table and the shipping checklist (sections 8 and 12) apply to every screen.

## Adaptations for a desktop operations tool

1. **Midnight is the default theme.** The owner wants the app dark first. Paper (light) is
   the alternative on the theme button. Keep the existing mechanism (`data-theme` on
   `<html>`, `public/theme-init.js`, `localStorage` key `rp-theme`): no attribute means
   Midnight, `data-theme="light"` means Paper.
2. **Margins and width.** Side margin 24 px from 1024 px wide, 32 px from 1440 px; 16 px
   below 768 px. Nothing touches the edge.
3. **Navigation.** On desktop, the floating tab bar (6.8) becomes a **glass capsule in the
   top bar**: the screens (Overview, Upload, Cases, Sign-off, MI, Audit log) sit in it,
   the current one under a gradient-tinted lens that springs between items (320–420 ms).
   The cases count is a gradient count pill. Fund, day, search (Ctrl K), role, theme and
   user are glass controls at the right. Below 768 px, the screens move to the floating
   bottom capsule exactly as 6.8 describes.
4. **Density.** Table rows in work queues (case queue, audit log, MI tables) are 44 px
   minimum, not 56–64. Plain lists elsewhere keep 56–64. Every target stays at least
   44 × 44 px, including on dense rows.
5. **Buttons.** The primary pill is 54 px below 1024 px and 44 px (radius 22) on desktop.
   Still one primary per screen: Approve on the workbench, Sign off on sign-off, Run on
   upload, Verify chain on the audit log. Reject and Reclassify are secondary pills.
6. **Amounts.** Amounts are in USD with en-US grouping (406,767,328.56) and signed where
   the meaning needs it (+150,740.90). Basis points read `+4.00 bp`. Right-aligned,
   tabular, on one line.
7. **Status words.** Pending or waiting → amber; Approved, signed off, met, intact → green;
   Rejected, blocked, breach, failed, broken chain → red; Reclassified and *AI disagrees*
   → info blue; Material, Escalated and Past SLA → neutral tags. Every one carries its word.
8. **One lead card per screen**, full width and first, as section 6.1:
   - Overview: NAV per share and the release status (Blocked / Ready to sign off), NAV in USD
     and the day-on-day move as its caption. This replaces the old NAV strip there; on
     other screens the NAV strip shrinks to a quiet one-line record under the top bar.
   - Cases: the selected case's NAV impact (USD and bp) with its status pill.
   - Sign-off: the release status and whether the four-eyes rule is satisfied.
   - Upload and run: the day's run status.
   - MI: gross open NAV impact across the period.
   - Audit log: chain integrity (Intact, with the entry count, or the first broken entry).
   - Administration and funds: the count of active users, or of funds.
9. **Tiles** (6.2) carry the overview's secondary figures (net impact, material count,
   open cases, oldest break) and MI's headline figures, two to four per row on desktop.

## Our own touches

- **The done moment (6.13) on sign-off.** After a successful sign-off: the green tick drawn
  in a ring, a dark pill "Signing off" → "Signed off", the day's summary card, and "Go to
  the next day" as the primary. A quick Undo toast follows case decisions where the API
  allows undo; where it does not, the toast simply confirms in words.
- **Ageing and SLA as calm tracks (6.14).** Business days open is drawn as a thin 6 px grey
  track filling with age; past SLA in muted red, inside SLA in grey, resolved in green,
  with a single accent "Today" tick on history views.
- **Count-up on the lead figure** (700–1100 ms, ease-out cubic) when a day loads or
  changes, off under reduced motion.
- **Mono ledger labels.** Section headers that name a register (OPEN BREAKS, EVIDENCE,
  RELEASE CHECKS, AUDIT TRAIL) use the mono label style above a sentence-case heading.

## Must not change

- Behaviour, routes, API calls, keyboard shortcuts, the command palette, wording rules.
- Accessibility: WCAG 2.2 AA contrast in both themes (check the muted greys and status
  colours on every surface), visible focus rings (2 px `--accent-a`, offset 2 px), live
  regions, status never by colour alone, usable at 200 % zoom. The axe and keyboard
  Playwright suites must still pass.
- Tests: update selectors only where markup genuinely changed; never weaken an assertion.
