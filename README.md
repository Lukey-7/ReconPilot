# ReconPilot

Daily fund reconciliation, break triage and NAV checks, built the way a fund
operations team actually works through the morning.

Every business day a fund administrator compares three records: the fund's own
trades and positions, the custodian's holdings statement, and the custodian's
cash statement. Anything that does not agree is a break. Breaks have to be
found, explained, chased with the custodian and signed off before the NAV goes
out. ReconPilot does that loop end to end on synthetic data and measures how
well it does it.

## What it does

1. **Matches the book against the custodian.** Positions are compared on
   quantity and price. Cash is matched in passes, strictest first: exact
   reference and amount, reference within tolerance, security and amount when
   the custodian leaves the reference blank, and many-to-one when the custodian
   nets several trades into one settlement line.
2. **Groups breaks into cases and suggests a cause.** A missing trade shows up
   as a quantity difference *and* an unexplained cash line, so breaks on the
   same security become one case. A set of rules then suggests the likely
   cause (missing trade, price mismatch, stock split, dividend, FX difference
   or late settlement), with a confidence score, an explanation that quotes
   the actual figures, and a draft query to send to the custodian.
3. **Calculates the NAV and runs the release checks.** Stale prices, missing
   prices, NAV movement against a threshold, and a cash tie-out that shows how
   much of the custodian/book cash gap is explained by open breaks.
4. **Keeps a person in charge.** Nothing closes automatically. Analysts approve,
   reject (with a reason) or reclassify each case. Only an approver can sign
   off the day, and not one who reviewed any of the cases (four-eyes rule).
   Viewers can read but not act.
5. **Logs everything in a tamper-evident audit trail.** Each entry carries the
   SHA-256 hash of the one before, so an edited, deleted or reordered line is
   detected by `reconpilot verify-audit`.
6. **Produces the Excel exception report** the team works from: summary,
   exceptions with explanations and draft queries, raw breaks, cash matching
   detail and NAV checks.

No real data is used anywhere. All funds, securities and statements are
generated.

## Measuring it honestly

The data generator deliberately plants known breaks and writes an answer key
(`planted_breaks.json`). The evaluator runs the full pipeline over many days and
checks three things:

- **Detection:** was a case raised on the security where a break was planted?
- **Classification:** was the suggested cause the right one?
- **False alarms:** how many cases were raised where nothing was planted?

Normal days are deliberately untidy even without planted breaks: the custodian
rounds some amounts by a few cents, nets trades together, and some book prices
are stale. None of that should produce a case.

Results over 20 business days with 200 planted breaks (seed 42):

| Data | Detected | Correct cause | False alarms |
|---|---|---|---|
| Standard | 200/200 (100%) | 200/200 (100%) | 0/200 (0%) |
| Hard | 190/200 (95.0%) | 178/190 (93.7%) | 8/198 (4.0%) |

The standard figures should be read with care: the rules and the generator
were written together, so a perfect score shows the logic is internally
consistent, not that it would score the same on real statements. The hard mode
exists to put pressure on it. It makes the custodian:

- post some dividends with no security identifier and a vague narrative,
- report price and FX differences small enough to sit near the tolerances,
- leave references off some cash lines,
- omit pending settlements from the statement, so a late trade looks like a
  missing one.

Where it goes wrong under hard data is visible in the confusion matrix in
[docs/evaluation.md](docs/evaluation.md): 12 late settlements are suggested as
missing trades (there is no pending line to tell them apart), and 9 dividends
with no security identifier are not attached to the right holding, which is
also where the false alarms come from.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run a sample day end to end:

```bash
reconpilot demo --dir demo
```

This writes the input CSVs to `demo/data`, the cases, audit log and Excel
report to `demo/run`, and prints a summary:

```
2026-11-13: 34 cash matches, 18 breaks, 12 cases
  EX-20261113-001  DE0000316491   PRICE_MISMATCH  0.85
  EX-20261113-002  DE0000493649   MISSING_TRADE   0.90
  EX-20261113-004  JP0000512651   TIMING          0.90
  EX-20261113-007  US0000275807   STOCK_SPLIT     0.95
  EX-20261113-009  GB0000482048   FX_DIFFERENCE   0.80
  EX-20261113-011  US0000165476   DIVIDEND        0.90
  ...
NAV per share 45.962456 (+0.74%)
  [WARN] Stale prices
  [PASS] Missing prices
  [PASS] NAV movement
  [WARN] Cash tie-out
```

## The daily workflow

```bash
# 1. Generate a day (or drop in your own CSVs in the same layout)
reconpilot generate --as-of 2026-11-13 --out data/2026-11-13 --breaks 12

# 2. Reconcile, raise cases, check the NAV, write the report
reconpilot run --data data/2026-11-13 --out runs/2026-11-13 --user priya

# 3. Review cases one at a time...
reconpilot review --run runs/2026-11-13 --user priya --case EX-20261113-001 --approve
reconpilot review --run runs/2026-11-13 --user priya --case EX-20261113-002 \
    --reclassify UNKNOWN --note "broker confirms no trade, chasing custodian"

# ...or in bulk from a CSV with columns case_id,decision,category,note
reconpilot review --run runs/2026-11-13 --user priya --decisions decisions.csv

# 4. A different person signs off
reconpilot signoff --run runs/2026-11-13 --user tom --role approver

# 5. Check nobody has edited the audit trail
reconpilot verify-audit --run runs/2026-11-13

# Score the pipeline
reconpilot evaluate --days 20 --breaks 10
reconpilot evaluate --days 20 --breaks 10 --hard
```

## Input files

| File | Contents |
|---|---|
| `book_trades.csv` | Fund's trades: id, dates, security, side, quantity, price, currency, FX rate, fees, settlement cash |
| `book_positions.csv` | Fund's positions with price and price date |
| `custodian_holdings.csv` | Custodian's holdings statement |
| `custodian_cash.csv` | Custodian's cash statement, in base currency, including lines value-dated in the future |
| `securities.csv`, `fx_rates.csv`, `fund.csv` | Static data, rates, opening cash, prior NAV, shares in issue |
| `planted_breaks.json` | Answer key (generated data only) |

## Project layout

```
src/reconpilot/
  generator.py   synthetic days with planted breaks
  matching.py    position and cash matching, tolerances
  triage.py      grouping breaks into cases, suggested causes, draft queries
  nav.py         NAV and release checks
  review.py      approve / reject / reclassify, roles, four-eyes sign-off
  audit.py       hash-chained audit log
  report.py      Excel exception report
  evaluate.py    scoring against the answer key
  storage.py     CSV and JSON reading and writing
  cli.py         command line
tests/           unit and end-to-end tests
```

Run the tests with `pytest`.

## Limitations and next steps

- One fund, one base currency (USD), equities only. No bonds, accrued
  interest, or multi-currency cash accounts.
- Settlement cash is held in base currency; real custodians usually report
  cash per currency account.
- Cases are matched to the answer key by security, so a break that spans two
  securities would be scored as two.
- Tolerances are global; in practice they vary by asset class and client.

Planned: per-currency cash accounts, ageing of open breaks across days, and
measuring analyst time per case with and without the suggested causes.

## Licence

MIT
