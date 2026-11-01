# Weekly AI forecast memo — 2026-11-01

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-01 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-11-01 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-11-01 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-11-01 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-11-01 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 38 | 1.1036 | 1.1310 | 1.0891 |
| laliga | 37 | 0.8967 | 1.0923 | 0.9729 |
| bundesliga | 36 | 1.0611 | 1.2169 | 1.1045 |
| seriea | 46 | 0.8246 | 1.0142 | 0.8985 |
| ligue1 | 34 | 0.8561 | 0.8393 | 0.7959 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 10 | 0.371 | 0.500 |
| 0.4-0.5 | 12 | 0.440 | 0.500 |
| 0.5-0.6 | 8 | 0.562 | 0.375 |
| 0.6-0.7 | 3 | 0.657 | 0.333 |
| 0.7-0.8 | 4 | 0.751 | 0.500 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 5 | 0.377 | 0.400 |
| 0.4-0.5 | 14 | 0.458 | 0.429 |
| 0.5-0.6 | 6 | 0.549 | 0.500 |
| 0.6-0.7 | 4 | 0.626 | 0.750 |
| 0.7-0.8 | 5 | 0.769 | 0.400 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 6 | 0.387 | 0.167 |
| 0.4-0.5 | 16 | 0.448 | 0.375 |
| 0.5-0.6 | 5 | 0.560 | 0.800 |
| 0.6-0.7 | 7 | 0.647 | 0.286 |
| 0.7-0.8 | 2 | 0.752 | 0.500 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 7 | 0.389 | 0.429 |
| 0.4-0.5 | 12 | 0.444 | 0.583 |
| 0.5-0.6 | 13 | 0.558 | 0.538 |
| 0.6-0.7 | 10 | 0.623 | 0.900 |
| 0.7-0.8 | 4 | 0.735 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 2 | 0.377 | 0.000 |
| 0.4-0.5 | 9 | 0.442 | 0.444 |
| 0.5-0.6 | 8 | 0.555 | 0.250 |
| 0.6-0.7 | 8 | 0.647 | 1.000 |
| 0.7-0.8 | 7 | 0.733 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0891 vs walk-forward 0.9990 (delta +0.0900, n=38) — DECAY FLAG.
- laliga: ledger 0.9729 vs walk-forward 0.9903 (delta -0.0174, n=37) — ok.
- bundesliga: ledger 1.1045 vs walk-forward 1.0083 (delta +0.0962, n=36) — DECAY FLAG.
- seriea: ledger 0.8985 vs walk-forward 1.0030 (delta -0.1045, n=46) — ok.
- ligue1: ledger 0.7959 vs walk-forward 1.0263 (delta -0.2304, n=34) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._