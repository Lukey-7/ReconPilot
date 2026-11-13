# Evaluation results

Produced by `reconpilot evaluate` and `reconpilot evaluate --hard`.

## Standard data (seed 42)

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

## Hard data (seed 42)

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
