# Evaluation results

All figures come from `reconpilot evaluate` over 20 business days with 200
planted breaks (seed 42). AI runs used medium reasoning effort, prompt version
`2026-11-14.1`, and are reproducible from the response cache.

## Hard data: rules versus AI

| | Rules only | AI (gpt-6-luna) | AI (gemini-3.8-flash) |
|---|---|---|---|
| Breaks detected | 190/200 (95.0%) | 190/200 (95.0%) | 190/200 (95.0%) |
| Correct cause (of detected) | 178/190 (93.7%) | 190/190 (100.0%) | 190/190 (100.0%) |
| False alarms | 8/198 (4.0%) | 8/198 (4.0%) | 8/198 (4.0%) |
| Correct: MISSING_TRADE | 34/34 | 34/34 | 34/34 |
| Correct: PRICE_MISMATCH | 33/34 | 33/34 | 33/34 |
| Correct: STOCK_SPLIT | 33/33 | 33/33 | 33/33 |
| Correct: DIVIDEND | 24/33 | 24/33 | 24/33 |
| Correct: FX_DIFFERENCE | 33/33 | 33/33 | 33/33 |
| Correct: TIMING | 21/33 | 33/33 | 33/33 |
| AI responses accepted | n/a | 198/198 | 198/198 |
| Fell back to rules | n/a | 0 | 0 |
| Disagreed with rules (AI right / rules right) | n/a | 12 (12 / 0) | 12 (12 / 0) |

Notes on reading this table:

- **Detection and false alarms cannot change.** The AI never raises, merges or
  closes cases; it only gives a second opinion on cases the engine raised.
- **All 12 AI gains are late settlements** where the custodian reported no
  pending line. The rules call these missing trades; both models judged them
  late settlements from the trade and settlement dates. The prompt's
  definition of TIMING explicitly allows for a settlement the custodian has
  not reported yet, so part of this gain comes from that definition. On real
  statements an unreported trade can genuinely be missing, which is why every
  disagreement is flagged for an analyst rather than applied.
- **The 8 false alarms are dividends posted with no security identifier**
  (9 planted dividends; one day had two in the same case). Both models labelled
  all 8 cases DIVIDEND, where the rules said UNKNOWN, but the scorer ties cases
  to planted breaks by security, so they still count as missed dividends and
  false alarms. Attaching the payment to the right holding needs information
  the custodian did not send.
- No response failed the guardrails in these runs (no fallbacks). The
  guardrails are exercised in `tests/test_ai.py` with malformed, invented and
  out-of-range responses.

## Standard data (rules only)

## Rules only (standard data)

20 business days, 200 planted breaks, 200 cases raised.

| Metric | Value |
|---|---|
| Breaks detected | 200/200 (100.0%) |
| Cause correctly suggested (of detected) | 200/200 (100.0%) |
| False alarms (cases with nothing planted) | 0/200 (0.0%) |

| Planted cause | Planted | Detected | Correct cause |
|---|---|---|---|
| MISSING_TRADE | 34 | 34 | 34 |
| PRICE_MISMATCH | 34 | 34 | 34 |
| STOCK_SPLIT | 33 | 33 | 33 |
| DIVIDEND | 33 | 33 | 33 |
| FX_DIFFERENCE | 33 | 33 | 33 |
| TIMING | 33 | 33 | 33 |

Confusion matrix (rows: planted, columns: suggested; MISSED = no case raised)

| | MISSING_TRADE | PRICE_MISMATCH | STOCK_SPLIT | DIVIDEND | FX_DIFFERENCE | TIMING | UNKNOWN | MISSED |
|---|---|---|---|---|---|---|---|---|
| MISSING_TRADE | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PRICE_MISMATCH | 0 | 34 | 0 | 0 | 0 | 0 | 0 | 0 |
| STOCK_SPLIT | 0 | 0 | 33 | 0 | 0 | 0 | 0 | 0 |
| DIVIDEND | 0 | 0 | 0 | 33 | 0 | 0 | 0 | 0 |
| FX_DIFFERENCE | 0 | 0 | 0 | 0 | 33 | 0 | 0 | 0 |
| TIMING | 0 | 0 | 0 | 0 | 0 | 33 | 0 | 0 |

## Detail: hard data

## Rules only (hard data)

20 business days, 200 planted breaks, 198 cases raised.

| Metric | Value |
|---|---|
| Breaks detected | 190/200 (95.0%) |
| Cause correctly suggested (of detected) | 178/190 (93.7%) |
| False alarms (cases with nothing planted) | 8/198 (4.0%) |

| Planted cause | Planted | Detected | Correct cause |
|---|---|---|---|
| MISSING_TRADE | 34 | 34 | 34 |
| PRICE_MISMATCH | 34 | 33 | 33 |
| STOCK_SPLIT | 33 | 33 | 33 |
| DIVIDEND | 33 | 24 | 24 |
| FX_DIFFERENCE | 33 | 33 | 33 |
| TIMING | 33 | 33 | 21 |

Confusion matrix (rows: planted, columns: suggested; MISSED = no case raised)

| | MISSING_TRADE | PRICE_MISMATCH | STOCK_SPLIT | DIVIDEND | FX_DIFFERENCE | TIMING | UNKNOWN | MISSED |
|---|---|---|---|---|---|---|---|---|
| MISSING_TRADE | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PRICE_MISMATCH | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 1 |
| STOCK_SPLIT | 0 | 0 | 33 | 0 | 0 | 0 | 0 | 0 |
| DIVIDEND | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 9 |
| FX_DIFFERENCE | 0 | 0 | 0 | 0 | 33 | 0 | 0 | 0 |
| TIMING | 12 | 0 | 0 | 0 | 0 | 21 | 0 | 0 |

## AI (gpt-6-luna) (hard data)

20 business days, 200 planted breaks, 198 cases raised.

| Metric | Value |
|---|---|
| Breaks detected | 190/200 (95.0%) |
| Cause correctly suggested (of detected) | 190/190 (100.0%) |
| False alarms (cases with nothing planted) | 8/198 (4.0%) |
| AI responses accepted by the guardrails | 198/198 |
| Fell back to rules | 0/198 |
| AI disagreed with rules (planted cases) | 12 (AI right 12, rules right 0) |

| Planted cause | Planted | Detected | Correct cause |
|---|---|---|---|
| MISSING_TRADE | 34 | 34 | 34 |
| PRICE_MISMATCH | 34 | 33 | 33 |
| STOCK_SPLIT | 33 | 33 | 33 |
| DIVIDEND | 33 | 24 | 24 |
| FX_DIFFERENCE | 33 | 33 | 33 |
| TIMING | 33 | 33 | 33 |

Confusion matrix (rows: planted, columns: suggested; MISSED = no case raised)

| | MISSING_TRADE | PRICE_MISMATCH | STOCK_SPLIT | DIVIDEND | FX_DIFFERENCE | TIMING | UNKNOWN | MISSED |
|---|---|---|---|---|---|---|---|---|
| MISSING_TRADE | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PRICE_MISMATCH | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 1 |
| STOCK_SPLIT | 0 | 0 | 33 | 0 | 0 | 0 | 0 | 0 |
| DIVIDEND | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 9 |
| FX_DIFFERENCE | 0 | 0 | 0 | 0 | 33 | 0 | 0 | 0 |
| TIMING | 0 | 0 | 0 | 0 | 0 | 33 | 0 | 0 |

## AI (gemini-3.8-flash) (hard data)

20 business days, 200 planted breaks, 198 cases raised.

| Metric | Value |
|---|---|
| Breaks detected | 190/200 (95.0%) |
| Cause correctly suggested (of detected) | 190/190 (100.0%) |
| False alarms (cases with nothing planted) | 8/198 (4.0%) |
| AI responses accepted by the guardrails | 198/198 |
| Fell back to rules | 0/198 |
| AI disagreed with rules (planted cases) | 12 (AI right 12, rules right 0) |

| Planted cause | Planted | Detected | Correct cause |
|---|---|---|---|
| MISSING_TRADE | 34 | 34 | 34 |
| PRICE_MISMATCH | 34 | 33 | 33 |
| STOCK_SPLIT | 33 | 33 | 33 |
| DIVIDEND | 33 | 24 | 24 |
| FX_DIFFERENCE | 33 | 33 | 33 |
| TIMING | 33 | 33 | 33 |

Confusion matrix (rows: planted, columns: suggested; MISSED = no case raised)

| | MISSING_TRADE | PRICE_MISMATCH | STOCK_SPLIT | DIVIDEND | FX_DIFFERENCE | TIMING | UNKNOWN | MISSED |
|---|---|---|---|---|---|---|---|---|
| MISSING_TRADE | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PRICE_MISMATCH | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 1 |
| STOCK_SPLIT | 0 | 0 | 33 | 0 | 0 | 0 | 0 | 0 |
| DIVIDEND | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 9 |
| FX_DIFFERENCE | 0 | 0 | 0 | 0 | 33 | 0 | 0 | 0 |
| TIMING | 0 | 0 | 0 | 0 | 0 | 33 | 0 | 0 |

