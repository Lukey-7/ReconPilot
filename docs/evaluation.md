# Evaluation results

All figures come from `reconpilot evaluate`, seed 42, except the carried-case
check, which comes from `scripts/ai_carried_check.py` (seed 21). AI runs used
medium reasoning effort and prompt version `2026-11-14.1`, and are reproducible
from the response cache.

There are two kinds of evaluation:

- **Single-day** (`reconpilot evaluate`): 20 independent business days, 200
  planted breaks. Scores detection and the suggested cause.
- **Multi-day** (`reconpilot evaluate --multi-day`): one fund over 20
  consecutive business days, 10 new breaks a day, each fixed 1 to 6 business
  days later. Scores the lifecycle: ageing, automatic clearing and the cause
  recorded when a case is resolved.

## Single-day, hard data: rules versus AI

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

- **Detection and false alarms cannot change.** The AI never raises, merges or
  closes cases; it only gives a second opinion on cases the engine raised.
- **The AI gains are late settlements** where the custodian reported no
  pending line. The rules call these missing trades; both models judged them
  late from the trade and settlement dates. The prompt's definition of TIMING
  allows for a settlement the custodian has not reported yet, so part of this
  gain comes from that definition; on real statements an unreported trade can
  genuinely be missing, which is why every disagreement goes to an analyst.
- **The false alarms are dividends posted with no security identifier.** Both
  models label these cases DIVIDEND where the rules say UNKNOWN, but the scorer
  ties cases to planted breaks by security, so they still count as missed
  dividends and false alarms.

## Multi-day, hard data: rules versus AI

`reconpilot evaluate --multi-day --hard --ai` with gpt-6-luna: 598 AI calls
(every open case is re-assessed each day), 597 accepted by the guardrails and
one fallback to the rules (an explanation quoting a figure not in the
evidence).

| | Rules only | AI (gpt-6-luna) |
|---|---|---|
| Detected on the day they appeared | 190/200 (95.0%) | 190/200 (95.0%) |
| Cause right on the first day (of detected) | 178/190 (93.7%) | 189/190 (99.5%) |
| Cleared automatically on the fix day | 160/167 (95.8%) | 160/167 (95.8%) |
| Cleared before the data was fixed | 0 | 0 |
| Cause right at resolution (of cleared) | 157/160 (98.1%) | 160/160 (100.0%) |
| Cases with no planted break (false alarms) | 1/191 (0.5%) | 1/191 (0.5%) |
| Average business days to resolve | 3.16 | 3.16 |
| Open at the end (0-1 / 2-5 / >5 days) | 17 / 13 / 1 | 17 / 13 / 1 |
| Open at the end: escalated / SLA breached | 5 / 2 | 5 / 2 |

| Planted cause | Rules only: right on day one / cleared on fix day / right at resolution | AI (gpt-6-luna): right on day one / cleared on fix day / right at resolution |
|---|---|---|
| MISSING_TRADE | 34/34 / 30/30 / 30/30 | 34/34 / 30/30 / 30/30 |
| PRICE_MISMATCH | 34/34 / 26/26 / 26/26 | 34/34 / 26/26 / 26/26 |
| STOCK_SPLIT | 33/33 / 25/25 / 25/25 | 33/33 / 25/25 / 25/25 |
| DIVIDEND | 22/33 / 19/26 / 18/19 | 23/33 / 19/26 / 19/19 |
| FX_DIFFERENCE | 31/33 / 30/30 / 28/30 | 33/33 / 30/30 / 30/30 |
| TIMING | 24/33 / 30/30 / 30/30 | 32/33 / 30/30 / 30/30 |

- **The lifecycle does not depend on the AI.** Detection, clearing, ageing,
  escalation and SLAs are identical: the AI explains cases, it never raises,
  clears or ages them.
- **The cause is right more often on day one and at resolution.** Late
  settlements the custodian had not reported, FX differences and an
  unidentified dividend are named correctly on the day they appear, and every
  cleared case is recorded with the right cause.

### Carried cases

A case carried into later days used to lose the context it was first
diagnosed with: the original trade was no longer in that day's files, so the
AI saw less evidence than on day one, and when the rules kept their earlier
diagnosis the "AI disagrees: needs review" flag was not recomputed. Both are
fixed in the engine (the carried item keeps its trade, and the flag is judged
again after the diagnosis is carried). `scripts/ai_carried_check.py` measures
it on an 8-day hard run (seed 21, 6 new breaks a day), counting every open
case each day against the planted break live on its security:

| gpt-6-luna, 8 days, seed 21 | Before the fixes | After |
|---|---|---|
| New cases (first day): rules right | 41/44 | 41/44 (93.2%) |
| New cases (first day): AI right | 44/44 | 44/44 (100.0%) |
| Carried cases (day two onwards): rules right | 74/75 | 74/75 (98.7%) |
| Carried cases (day two onwards): AI right | 54/75 | 75/75 (100.0%) |
| Disagreements with the rules not flagged | 20 | 0 |

All 126 AI answers (119 live calls, 7 from the cache) passed the guardrails.
The AI is now at least as accurate on carried cases as on new ones, and all 11
disagreements with the rules are flagged for an analyst.

## The web application

The web application runs the same engine, with the same prompts and
guardrails, so these figures hold for it too. A test runs the same multi-day
files through the command line and through the web application's pipeline and
requires identical cases, figures and audit actions, and the browser tests
check that every figure on screen is the API's.

Two things differ only in where the answers come from:

- **The public demo never calls a provider.** Its answers come from a cache
  built with gpt-6-luna (medium effort, prompt version `2026-11-14.1`) through
  the web application's own code for the demo's fixed sequence (seed 62, hard
  data, four new breaks a day, ten business days from 9 November 2026): 102
  answers, every one the demo asks for. A question not in the cache falls back
  to the rules, as with any failed call.
- **A private OpenAI-compatible endpoint** (for example a firm's own Azure
  OpenAI deployment) goes through the same guardrails, but it has not been
  measured here: its accuracy depends on the model behind it, and should be
  measured with `reconpilot evaluate --ai --ai-provider openai_compatible`
  before a fund's AI is switched on.

## Multi-day lifecycle (rules only)

## Standard and hard data, 20 consecutive business days

20 consecutive business days, 200 breaks planted, each fixed 1 to 6 business days later (late settlements 1 to 2 days).

| | Standard data | Hard data |
|---|---|---|
| Detected on the day they appeared | 200/200 (100.0%) | 190/200 (95.0%) |
| Cause right on the first day (of detected) | 200/200 (100.0%) | 178/190 (93.7%) |
| Cleared automatically on the fix day | 169/169 (100.0%) | 160/167 (95.8%) |
| Cleared before the data was fixed | 0 | 0 |
| Cause right at resolution (of cleared) | 169/169 (100.0%) | 157/160 (98.1%) |
| Cases with no planted break (false alarms) | 0/200 (0.0%) | 1/191 (0.5%) |
| Average business days to resolve | 3.17 | 3.16 |
| Open at the end (0-1 / 2-5 / >5 days) | 19 / 12 / 0 | 17 / 13 / 1 |
| Open at the end: escalated / SLA breached | 9 / 2 | 5 / 2 |

| Planted cause | Standard data: right on day one / cleared on fix day / right at resolution | Hard data: right on day one / cleared on fix day / right at resolution |
|---|---|---|
| MISSING_TRADE | 34/34 / 30/30 / 30/30 | 34/34 / 30/30 / 30/30 |
| PRICE_MISMATCH | 34/34 / 26/26 / 26/26 | 34/34 / 26/26 / 26/26 |
| STOCK_SPLIT | 33/33 / 26/26 / 26/26 | 33/33 / 25/25 / 25/25 |
| DIVIDEND | 33/33 / 27/27 / 27/27 | 22/33 / 19/26 / 18/19 |
| FX_DIFFERENCE | 33/33 / 30/30 / 30/30 | 31/33 / 30/30 / 28/30 |
| TIMING | 33/33 / 30/30 / 30/30 | 24/33 / 30/30 / 30/30 |

- **Nothing clears early.** A case clears only on the day the data actually
  agrees again, never before the planted fix.
- **Waiting a day resolves the late settlements.** On hard data some late
  settlements look like missing trades on the day they appear; when the
  custodian settles them, the case clears and is recorded as a late settlement,
  so the cause at resolution is right for every one of them. This is the same
  weakness the AI addresses on day one, fixed instead by the passage of time.
- **Dividends with no security identifier remain the hard case.** They are
  grouped together under no security, so they neither score as detected nor
  clear until every one of them is booked.
- The rules-versus-AI comparison over the same 20 days is in the section
  above. With `--ai` every open case is re-assessed each day, and carried
  cases whose evidence changes cost a new call.

## Single-day, standard data (rules only)

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

## Detail: single-day hard data

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

