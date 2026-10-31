# Weekly AI forecast memo — 2026-10-31

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-31 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-10-31 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-10-31 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-10-31 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-10-31 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 36 | 1.0941 | 1.1084 | 1.0730 |
| laliga | 33 | 0.9565 | 1.1081 | 1.0114 |
| bundesliga | 33 | 1.0517 | 1.1762 | 1.0905 |
| seriea | 41 | 0.8539 | 1.0592 | 0.9356 |
| ligue1 | 30 | 0.8611 | 0.8896 | 0.8246 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.372 | 0.556 |
| 0.4-0.5 | 12 | 0.440 | 0.500 |
| 0.5-0.6 | 8 | 0.562 | 0.375 |
| 0.6-0.7 | 2 | 0.637 | 0.500 |
| 0.7-0.8 | 4 | 0.751 | 0.500 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.374 | 0.250 |
| 0.4-0.5 | 13 | 0.456 | 0.462 |
| 0.5-0.6 | 5 | 0.551 | 0.400 |
| 0.6-0.7 | 4 | 0.626 | 0.750 |
| 0.7-0.8 | 5 | 0.769 | 0.400 |
| 0.8-0.9 | 2 | 0.838 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 6 | 0.387 | 0.167 |
| 0.4-0.5 | 14 | 0.446 | 0.429 |
| 0.5-0.6 | 5 | 0.560 | 0.800 |
| 0.6-0.7 | 6 | 0.649 | 0.333 |
| 0.7-0.8 | 2 | 0.752 | 0.500 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 6 | 0.390 | 0.333 |
| 0.4-0.5 | 12 | 0.444 | 0.583 |
| 0.5-0.6 | 11 | 0.558 | 0.455 |
| 0.6-0.7 | 9 | 0.625 | 0.889 |
| 0.7-0.8 | 3 | 0.743 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.368 | 0.000 |
| 0.4-0.5 | 9 | 0.442 | 0.444 |
| 0.5-0.6 | 8 | 0.555 | 0.250 |
| 0.6-0.7 | 6 | 0.641 | 1.000 |
| 0.7-0.8 | 6 | 0.732 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0730 vs walk-forward 0.9990 (delta +0.0740, n=36) — DECAY FLAG.
- laliga: ledger 1.0114 vs walk-forward 0.9903 (delta +0.0211, n=33) — ok.
- bundesliga: ledger 1.0905 vs walk-forward 1.0083 (delta +0.0822, n=33) — DECAY FLAG.
- seriea: ledger 0.9356 vs walk-forward 1.0030 (delta -0.0674, n=41) — ok.
- ligue1: ledger 0.8246 vs walk-forward 1.0263 (delta -0.2017, n=30) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._