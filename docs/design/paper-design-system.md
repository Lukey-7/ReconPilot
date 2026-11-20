# Paper: the KiranOS design system, for any website

Paper is the look built for the KiranOS iPhone app: warm paper by day, a cool midnight by night,
one contrast card per page for the number that matters, and a blue-to-violet gradient used as an
**accent only**. This guide is everything needed to give a website the same feel: the
principles, every token, the type, the icons, each component, the motion, and code to paste.

Reference builds: the demo web app in `demo/` (run `npm run dev`, port 5301) and the phone layer
(`ios-app/mobile/src/apps/phone-paper.css` on the local branch).

---

## 1. Five principles

1. **Calm base, one bright thing.** The page is quiet paper (or midnight). Each page has one
   lead card in strong contrast (dark on paper, paper on midnight) for its headline figure.
2. **Gradient is an accent, never a theme.** Use it on at most a few small things per screen:
   the page's top glow, the lead card's top edge, the current tab, avatars, counts, a progress
   ring. Never on backgrounds of lists, rows, forms or body text.
3. **Colour means status, always with a word.** Red = late or wrong, amber = waiting, green =
   done. A coloured dot or pill always carries its word ("Overdue", not just red).
4. **Numbers line up.** Figures use tabular digits, sit on one line, and a row of tiles keeps
   its figures level. Amounts are right-aligned in lists.
5. **Professional, not playful.** Muted greys, small mono labels, thin hairlines, short motion
   (under 600 ms). Colour comes from status and the one accent, not decoration.

---

## 2. Colour

### 2.1 Paper (light)

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#F4F1EA` | Page background (warm paper) |
| `--surface` | `#FFFFFF` | Cards, lists, fields |
| `--surface-2` | `#EBE7DE` | Segmented track, tile icon box, pressed row, chip fill |
| `--ink` | `#14151B` | Main text, primary button fill |
| `--ink-2` | `#3A3C47` | Secondary text in rows |
| `--muted` | `#5F626E` | Labels, captions, inactive tabs |
| `--faint` | `#A3A6B3` | Chevrons, placeholders, disabled |
| `--line` | `rgba(20,21,27,0.09)` | Hairlines between rows, card borders |
| `--hero` | `#14151B` | Lead (contrast) card fill |
| `--hero-ink` | `#FFFFFF` | Text on the lead card |
| `--hero-muted` | `#A9ACBB` | Labels on the lead card |

### 2.2 Midnight (dark)

Not pure black. Layered cool greys, with a lit top edge on surfaces.

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0A0B10` | Page background |
| `--surface` | `#15161D` | Cards, lists (optionally `linear-gradient(180deg,#191A22,#14151C)`) |
| `--surface-2` | `#1D1F28` | Track, icon boxes, pressed row |
| `--ink` | `#F5F5F7` | Main text |
| `--ink-2` | `#DFE0E7` | Secondary text |
| `--muted` | `#9B9EB0` | Labels, captions |
| `--faint` | `#5F6270` | Chevrons, disabled |
| `--line` | `rgba(255,255,255,0.07)` | Hairlines, card borders |
| `--hero` | `#F4F1EA` | Lead card flips to **paper** in the dark |
| `--hero-ink` | `#14151B` | Text on the lead card |
| `--hero-muted` | `#6B6E7B` | Labels on the lead card |

### 2.3 Status (with a word, always)

| Meaning | Light text / soft bg | Dark text / soft bg |
|---|---|---|
| Late, wrong, low | `#C8363A` / `#FCE8E6` | `#FF6B6B` / `#3C1818` |
| Waiting, review | `#A6660C` / `#FAEED7` | `#F0B050` / `#34250E` |
| Done, approved | `#248054` / `#E2F3E9` | `#4CC38A` / `#122E20` |
| Neutral | `#5F626E` / `#EBE7DE` | `#9B9EB0` / `#1D1F28` |
| Info | `#466EE6` / `#E8EDFC` | `#8FB0FF` / `#1D1F28` |

### 2.4 The accent gradient

```css
--accent-a: #5B8CFF;   /* blue */
--accent-b: #A47CFF;   /* violet */
--accent: linear-gradient(135deg, var(--accent-a), var(--accent-b));
```

| Where | How |
|---|---|
| Page glow | Two radial washes at the top of `body`, 12 % opacity light, 20 % dark (code below). |
| Lead card edge | A 2 px line along its top: `linear-gradient(90deg,#5B8CFF,#A47CFF)`. Plus a soft radial halo in its top-right corner (24 % violet-blue). |
| Current tab / nav item | The gradient at 16–24 % opacity as the highlight, icon in `--accent-a` (`#8FB0FF` in dark). |
| Avatars | Gradient circles in four pairs, chosen by the name: blue→violet `#5B8CFF→#A47CFF`, teal→blue `#2FB59B→#3D7FE0`, amber→red `#E7A14B→#DD5C58`, pink→violet `#D25AA2→#8A63F0`. White initials. |
| Counts | Unread / badge pills filled with the gradient, white number. |
| Progress ring | Stroke with the gradient. |
| Big figure (optional) | Text clipped to `linear-gradient(90deg, ink 30%, #B9C9FF)` on the lead card only. |

**Never:** gradient page backgrounds, gradient buttons for every action, gradient text in
paragraphs, more than three gradient elements visible at once.

---

## 3. Type

| Role | Font | Size / line | Weight | Notes |
|---|---|---|---|---|
| Large title | Barlow | 32 / 38 | 700 | Page title, sentence case |
| Lead figure | Barlow | 38–44 / 44–46 | 700 | Tabular digits, `letter-spacing:-0.01em` |
| Tile figure | Barlow | 22 / 28 (shrinks to 16 for long amounts) | 700 | One line, tabular |
| Section heading | Barlow | 16 / 22 | 600 | Above a group, count beside it in muted |
| Row title | Barlow | 16 / 21 | 500 | |
| Body | Barlow | 15 / 21 | 400 | |
| Caption / row sub | Barlow | 13 / 18 | 400 | `--muted` |
| Tile label | Barlow | 13 / 18 | 500 | Up to two lines; every tile keeps two lines' room |
| Mono label | JetBrains Mono | 10.5 / 14, `letter-spacing:1px`, UPPERCASE | 400–500 | Codes (RM-0044, KP-112), month headers, department tags |
| Status pill | Barlow | 12.5 | 600 | |

```html
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

Rules:
- Every number in a figure, table or list: `font-variant-numeric: tabular-nums;`.
- Indian amounts with `toLocaleString('en-IN')`: ₹4,08,60,339. Compact on tiles when needed: ₹4.37 Cr.
- Sentence case everywhere ("Raise a requisition", not "Raise A Requisition").
- Never cut a label with "…" if two lines fit; never wrap a figure.

---

## 4. Icons

- **Set:** [Lucide](https://lucide.dev) (`lucide-react` / `lucide` / SVG). One set only.
- **Stroke:** 1.8 for navigation and tabs, 2 for inline icons, 2.4–2.6 for ticks in small circles.
- **Sizes:** 22 px tab bar, 20 px top-bar buttons, 18–20 px in rows and menus, 14–16 px inline
  with text, 26 px in app tiles.
- **Colour:** inherits text colour. Muted when inactive, ink when active, `--accent-a` for the
  current tab only.
- **Shape stays the same** in every state (don't swap outline for filled on selection; the size
  jumps). Show the state with colour and the highlight behind it.
- Icon boxes ("tiles"): 38–40 px, radius 12, `--surface-2` fill (dark: `linear-gradient(145deg,#262836,#1A1B24)` with `inset 0 1px 0 rgba(255,255,255,.07)`).

Common icons: `message-circle` Chat, `inbox` Inbox, `check-square` Projects, `sparkles` AI,
`search`, `menu` drawer, `chevron-left` back, `chevron-right` row, `sliders-horizontal` filter,
`share` export, `plus` new, `bell` notifications, `scan-line` barcode, `calendar`, `user-plus`.

---

## 5. Space, shape, depth

| Token | Value |
|---|---|
| Side margin | 16 px on phones, 20–32 px on desktop. **Nothing touches the screen edge.** |
| Spacing scale | 4, 6, 8, 10, 12, 16, 20, 24, 32 |
| Gap between cards | 10–12 px; between sections 22–24 px |
| Card radius | 20 px (lists, panels, tiles); lead card 24 px; small cards 16 px |
| Pills | Fully round: buttons 54 px high (radius 27), fields 44 (radius 22), chips 32–34, status 22–24 |
| Hairline | 0.5 px `--line` |
| Card shadow (light) | `0 1px 2px rgba(20,21,27,.04), 0 6px 18px rgba(20,21,27,.05)` |
| Card shadow (dark) | `inset 0 1px 0 rgba(255,255,255,.05), 0 10px 30px rgba(0,0,0,.35)` |
| Lead card shadow | light `0 16px 36px rgba(20,21,27,.22)`; dark `0 0 0 .5px rgba(255,255,255,.3), 0 18px 50px rgba(91,140,255,.18)` |
| Min touch target | 44 × 44 px |

---

## 6. Components

### 6.1 Lead (contrast) card
The page's headline number. One per page, full width, first.
- Fill `--hero`, text `--hero-ink`, label `--hero-muted`.
- 2 px gradient line on top, soft radial halo top-right.
- Label (13 px) → figure (38–44 px) → caption (13 px) → optional status pill or mini bar.
- Pops in (scale .94 → 1, 520 ms).

### 6.2 Figure tiles
Two per row under the lead card.
- `--surface`, radius 20, 14 px padding, card shadow.
- Top-down: label (two lines' room) → figure (one line) → note (up to two lines) → status pill at the foot.
- All tiles in a row equal height; figures level. A tile alone on the last row takes the full row.

### 6.3 Lists and rows
- A list is one rounded card; rows inside are separated by hairlines, no per-row boxes.
- Row: 56–64 px, 16 px left padding, `[lead icon/avatar] title + sub ……… value chevron`.
- Values right-aligned, tabular, bold. Status pill goes under the title, not beside it.
- On narrow screens, controls (Edit, Switch off, arrows) drop to a second line under the title.

### 6.4 Records (facts)
Label left in `--muted`, value right in `--ink`, one fact per row, hairline between. Values wrap
anywhere; labels never more than 45 % width.

### 6.5 Buttons
- **Primary:** one per screen. Pill, 54 px, `--ink` fill + white text (dark mode: paper fill + ink text). Soft coloured shadow `0 10px 28px rgba(91,140,255,.22)`.
- **Secondary:** pill, transparent, 0.5 px `--line` border, ink text.
- **Quiet / export:** 32 px chip, muted text, hairline border (Excel, CSV live here; never compete with the primary).
- **Disabled:** same style at 45 % opacity (not grey).
- Press: scale .97, 90 ms.

### 6.6 Fields
One shape for every field: 44 px high, radius 22, `--surface`, 0.5 px border, 16 px text
(prevents iOS zoom). Dates, months and times are centred. Fields never wider than their column.
File inputs get a styled pill button (`::file-selector-button`).

### 6.7 Segmented control / tabs
- Track `--surface-2`, radius 19, 3 px inset; the current option is a pill of `--ink` (paper in
  dark) with a spring slide (320 ms). Counts as small round badges.
- Rows of filter chips: 34 px pills, current one filled ink, others text only.

### 6.8 Navigation
- **Top bar:** glass buttons (40 px circles, `backdrop-filter: blur(24px)`, translucent surface, hairline, soft shadow) for menu/back and one action; large title below.
- **Side drawer:** the page turns away in depth to reveal it:
  `transform: perspective(1400px) translate3d(min(74vw,300px),0,0) rotateY(-16deg) scale(.84)`, radius 34, 560 ms. The current place gets the gradient tint.
- **Floating tab bar:** glass capsule 62 px high, 16 px from the sides and 22 px from the bottom, four places plus a separate round search button; the current place has a gradient-tinted lens that springs between items. It follows the app's light/dark.
- Section chips under the title scroll sideways; the current chip is gradient-tinted, not a second light pill.

### 6.9 Status pill
22–24 px, radius 12, 12.5 px semibold, soft background of the status colour, 6 px dot of the
status colour, then the word.

### 6.10 Empty states
Centred, 40 px vertical padding, a short sentence in `--ink-2`, one action at most. Never the
same action twice on a screen.

### 6.11 Loading
- 3 px gradient progress line sliding across the top.
- Shimmer rows in the shape of what's coming: `linear-gradient(90deg, shimmer-a, shimmer-b, shimmer-a)` at 760 px, 1.4 s linear (light `#E6E2D8/#F3F0E9`, dark `#181A22/#282B38`).
- Small spinner with a sentence ("Getting the latest stock").
- Real rows fade in over the shimmer, staggered.

### 6.12 Press-and-hold menu
Hold 420 ms (with a light haptic) → page dims and blurs (`--scrim`), the card lifts, an info bar
above it (status, due date, code), then a menu: a row of 4 quick actions (icon over word), then
plain items, destructive last in red.

### 6.13 Done moment
After an approval: a green tick drawn in a ring (800 ms + 450 ms), a dark status pill at the top
("Letting them know" → "Done"), a summary card, then "Next approval" primary and an Undo link.
Also an Undo toast for quick actions: dark (`--hero`) pill, 52 px, 4 s.

### 6.14 Board and timeline (calm)
- Board columns: `--surface-2`, radius 22; cards white with a mono department tag and code at the
  top, title, then status dot + word and a neutral avatar. No coloured column tops.
- Timeline: thin 6 px grey tracks filling with progress; late in muted red, done in green, on
  track in grey; a single "TODAY" line in the accent.

---

## 7. Motion

| Thing | Duration | Easing |
|---|---|---|
| Press | 90 ms | ease-out, scale .93–.97 |
| Rise in (cards, rows) | 480 ms | `cubic-bezier(.2,.7,.2,1)`, from 10–12 px below, staggered 40–80 ms |
| Lead card / menus pop | 300–520 ms | `cubic-bezier(.2,.85,.25,1.15)` (spring) |
| Segment / tab lens | 320–420 ms | spring |
| Screen push / back | 380 / 320 ms | `cubic-bezier(.2,.7,.2,1)` |
| Drawer | 560 ms | `cubic-bezier(.32,.72,0,1)` |
| Count-up figures | 700–1100 ms | ease-out cubic |
| Ring / tick draw | 800 / 450 ms | ease-out |

Always honour `prefers-reduced-motion: reduce` (turn all of it off).

---

## 8. Do and don't

| Do | Don't |
|---|---|
| One lead card, one primary button per page | Two bright pills side by side |
| Gradient on 2–3 small things | Gradient backgrounds or gradient on every button |
| Right-aligned tabular amounts | Centred or proportional numbers |
| Status colour + its word | A red dot with no word |
| 16 px margin everywhere | Cards or fields touching the screen edge |
| Midnight greys in dark mode | Pure `#000` everywhere |
| Short labels, one line of help at most | Paragraphs of explanation above the data |
| Exports as quiet chips | Excel/CSV as big pills above the main action |

---

## 9. Paste-ready CSS

```css
:root, [data-theme="paper"] {
  --bg:#F4F1EA; --surface:#FFFFFF; --surface-2:#EBE7DE;
  --ink:#14151B; --ink-2:#3A3C47; --muted:#5F626E; --faint:#A3A6B3;
  --line:rgba(20,21,27,.09);
  --hero:#14151B; --hero-ink:#FFFFFF; --hero-muted:#A9ACBB;
  --red:#C8363A; --red-soft:#FCE8E6; --amber:#A6660C; --amber-soft:#FAEED7;
  --green:#248054; --green-soft:#E2F3E9;
  --accent-a:#5B8CFF; --accent-b:#A47CFF;
  --accent:linear-gradient(135deg,var(--accent-a),var(--accent-b));
  --glow:.12;
  --card-shadow:0 1px 2px rgba(20,21,27,.04),0 6px 18px rgba(20,21,27,.05);
  --glass:rgba(255,255,255,.74); --glass-line:rgba(20,21,27,.10);
  --font:'Barlow',-apple-system,system-ui,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,monospace;
  --ease:cubic-bezier(.2,.7,.2,1); --spring:cubic-bezier(.2,.85,.25,1.15);
}
[data-theme="midnight"] {
  --bg:#0A0B10; --surface:#15161D; --surface-2:#1D1F28;
  --ink:#F5F5F7; --ink-2:#DFE0E7; --muted:#9B9EB0; --faint:#5F6270;
  --line:rgba(255,255,255,.07);
  --hero:#F4F1EA; --hero-ink:#14151B; --hero-muted:#6B6E7B;
  --red:#FF6B6B; --red-soft:#3C1818; --amber:#F0B050; --amber-soft:#34250E;
  --green:#4CC38A; --green-soft:#122E20;
  --glow:.20;
  --card-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 10px 30px rgba(0,0,0,.35);
  --glass:rgba(34,36,48,.66); --glass-line:rgba(255,255,255,.14);
}

body{
  margin:0; font-family:var(--font); color:var(--ink); background-color:var(--bg);
  -webkit-font-smoothing:antialiased;
  background-image:
    radial-gradient(80% 300px at 12% 0%, rgba(91,140,255,var(--glow)), transparent 70%),
    radial-gradient(60% 260px at 100% 0%, rgba(164,124,255,calc(var(--glow)*.8)), transparent 70%);
  background-repeat:no-repeat;
}
.num{font-variant-numeric:tabular-nums}
.mono{font-family:var(--mono);font-size:10.5px;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}

.card{background:var(--surface);border:.5px solid var(--line);border-radius:20px;box-shadow:var(--card-shadow)}

.lead{position:relative;overflow:hidden;padding:18px;border-radius:24px;
  background:var(--hero);color:var(--hero-ink);box-shadow:0 16px 36px rgba(20,21,27,.22)}
.lead::before{content:"";position:absolute;inset:0 0 auto;height:2px;background:var(--accent)}
.lead::after{content:"";position:absolute;right:-60px;top:-80px;width:220px;height:220px;border-radius:50%;
  background:radial-gradient(circle,rgba(124,132,255,.24),transparent 65%);pointer-events:none}
.lead .label{font-size:14px;color:var(--hero-muted)}
.lead .figure{font-size:40px;line-height:46px;font-weight:700;font-variant-numeric:tabular-nums}

.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.tile{display:flex;flex-direction:column;gap:4px;min-height:92px;padding:14px}
.tile .label{min-height:36px;font-size:13px;line-height:18px;font-weight:500;color:var(--muted);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tile .figure{font-size:22px;line-height:28px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}

.row{display:flex;align-items:center;gap:12px;min-height:60px;padding:10px 14px 10px 16px;flex-wrap:wrap}
.row + .row{border-top:.5px solid var(--line)}
.row .value{margin-left:auto;font-weight:700;font-size:17px;font-variant-numeric:tabular-nums}

.btn{height:54px;padding:0 24px;border:0;border-radius:27px;font:600 17px var(--font);
  background:var(--ink);color:var(--bg);box-shadow:0 10px 28px rgba(91,140,255,.22);
  transition:transform 160ms var(--spring)}
.btn:active{transform:scale(.97)} .btn:disabled{opacity:.45}
.btn-quiet{height:32px;padding:0 12px;border:.5px solid var(--line);border-radius:16px;
  background:transparent;color:var(--muted);font:500 13px var(--font)}

.field{min-height:44px;width:100%;padding:0 16px;border:.5px solid var(--line);border-radius:22px;
  background:var(--surface);color:var(--ink);font:16px var(--font)}

.status{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:12px;
  font:600 12.5px var(--font)}
.status::before{content:"";width:6px;height:6px;border-radius:3px;background:currentColor}
.status.late{color:var(--red);background:var(--red-soft)}
.status.wait{color:var(--amber);background:var(--amber-soft)}
.status.done{color:var(--green);background:var(--green-soft)}

.glass{background:var(--glass);border:.5px solid var(--glass-line);
  backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);box-shadow:0 10px 30px rgba(20,21,27,.12)}

.avatar{display:grid;place-items:center;border-radius:50%;color:#fff;font-weight:600;background:var(--accent)}

.shimmer{border-radius:7px;background:linear-gradient(90deg,#E6E2D8,#F3F0E9,#E6E2D8);
  background-size:760px 100%;animation:shimmer 1.4s linear infinite}
[data-theme="midnight"] .shimmer{background-image:linear-gradient(90deg,#181A22,#282B38,#181A22)}

@keyframes shimmer{from{background-position:-380px 0}to{background-position:380px 0}}
@keyframes rise{from{opacity:0;transform:translateY(12px)}}
@keyframes pop{0%{opacity:0;transform:scale(.94)}70%{transform:scale(1.01)}}
.rise{animation:rise 480ms var(--ease) both}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
```

## 10. Tailwind (v3) config

```js
// tailwind.config.js
export default {
  darkMode: ['class', '[data-theme="midnight"]'],
  theme: {
    extend: {
      fontFamily: { sans: ['Barlow', 'system-ui', 'sans-serif'], mono: ['"JetBrains Mono"', 'monospace'] },
      colors: {
        paper: { bg: '#F4F1EA', surface: '#FFFFFF', 2: '#EBE7DE', ink: '#14151B', ink2: '#3A3C47', muted: '#5F626E', faint: '#A3A6B3' },
        night: { bg: '#0A0B10', surface: '#15161D', 2: '#1D1F28', ink: '#F5F5F7', ink2: '#DFE0E7', muted: '#9B9EB0', faint: '#5F6270' },
        accent: { a: '#5B8CFF', b: '#A47CFF' },
        status: { late: '#C8363A', wait: '#A6660C', done: '#248054' },
      },
      backgroundImage: { accent: 'linear-gradient(135deg,#5B8CFF,#A47CFF)' },
      borderRadius: { card: '20px', lead: '24px', pill: '9999px' },
      boxShadow: {
        card: '0 1px 2px rgba(20,21,27,.04), 0 6px 18px rgba(20,21,27,.05)',
        lead: '0 16px 36px rgba(20,21,27,.22)',
        glow: '0 10px 28px rgba(91,140,255,.22)',
      },
      transitionTimingFunction: { ios: 'cubic-bezier(.2,.7,.2,1)', spring: 'cubic-bezier(.2,.85,.25,1.15)' },
    },
  },
};
```

## 11. A page, top to bottom

1. Glow at the top of the page (body background).
2. Top bar: glass menu/back button left, one glass action right; large title; optional one-line subtitle in muted.
3. Section chips or a segmented control.
4. **Lead card** with the page's headline figure.
5. Two-up figure tiles.
6. Section heading ("Needs attention 3"), then one list card with rows and right-aligned amounts.
7. One primary button, if the page has an action.
8. Floating glass tab bar; content scrolls clear of it (bottom padding = bar height + 40 px).

## 12. Checklist before shipping a screen

- [ ] Nothing within 16 px of the screen edge; nothing overlapping.
- [ ] One lead card, one primary button.
- [ ] At most three gradient touches visible.
- [ ] Every figure tabular, on one line, level with its row.
- [ ] Every status colour has its word.
- [ ] Fields 44 px, same shape, none wider than its column.
- [ ] Works in Paper and Midnight; nothing pure black.
- [ ] Reduced motion turns animation off.
- [ ] Touch targets at least 44 px.
