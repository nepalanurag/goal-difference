# Weekly AI forecast memo — 2026-11-22

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-22 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-11-22 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-11-22 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-11-22 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-11-22 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 59 | 1.0803 | 1.1566 | 1.0908 |
| laliga | 58 | 0.9083 | 1.0851 | 0.9774 |
| bundesliga | 54 | 1.0004 | 1.1777 | 1.0519 |
| seriea | 68 | 0.8533 | 0.9775 | 0.8928 |
| ligue1 | 53 | 0.9438 | 0.9778 | 0.9143 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 17 | 0.370 | 0.529 |
| 0.4-0.5 | 16 | 0.446 | 0.562 |
| 0.5-0.6 | 13 | 0.558 | 0.385 |
| 0.6-0.7 | 5 | 0.648 | 0.400 |
| 0.7-0.8 | 6 | 0.749 | 0.500 |
| 0.8-0.9 | 2 | 0.824 | 0.500 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.379 | 0.222 |
| 0.4-0.5 | 23 | 0.456 | 0.391 |
| 0.5-0.6 | 8 | 0.539 | 0.625 |
| 0.6-0.7 | 8 | 0.635 | 0.750 |
| 0.7-0.8 | 7 | 0.762 | 0.571 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.388 | 0.250 |
| 0.4-0.5 | 24 | 0.449 | 0.458 |
| 0.5-0.6 | 8 | 0.552 | 0.750 |
| 0.6-0.7 | 10 | 0.637 | 0.500 |
| 0.7-0.8 | 3 | 0.750 | 0.667 |
| 0.8-0.9 | 1 | 0.827 | 0.000 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.382 | 0.444 |
| 0.4-0.5 | 19 | 0.447 | 0.526 |
| 0.5-0.6 | 20 | 0.557 | 0.600 |
| 0.6-0.7 | 14 | 0.628 | 0.857 |
| 0.7-0.8 | 6 | 0.724 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.374 | 0.250 |
| 0.4-0.5 | 18 | 0.450 | 0.500 |
| 0.5-0.6 | 11 | 0.551 | 0.273 |
| 0.6-0.7 | 12 | 0.657 | 0.833 |
| 0.7-0.8 | 8 | 0.729 | 0.875 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0908 vs walk-forward 0.9990 (delta +0.0917, n=59) — DECAY FLAG.
- laliga: ledger 0.9774 vs walk-forward 0.9903 (delta -0.0129, n=58) — ok.
- bundesliga: ledger 1.0519 vs walk-forward 1.0083 (delta +0.0437, n=54) — ok.
- seriea: ledger 0.8928 vs walk-forward 1.0030 (delta -0.1102, n=68) — ok.
- ligue1: ledger 0.9143 vs walk-forward 1.0263 (delta -0.1120, n=53) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._