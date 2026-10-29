# Weekly AI forecast memo — 2026-10-29

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-29 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-10-29 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-10-29 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-10-29 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-10-29 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 30 | 1.0872 | 1.0492 | 1.0416 |
| laliga | 30 | 0.9361 | 1.0649 | 0.9774 |
| bundesliga | 27 | 1.0456 | 1.1147 | 1.0647 |
| seriea | 38 | 0.8639 | 1.0735 | 0.9511 |
| ligue1 | 27 | 0.8766 | 0.9374 | 0.8551 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.372 | 0.625 |
| 0.4-0.5 | 8 | 0.444 | 0.625 |
| 0.5-0.6 | 7 | 0.560 | 0.429 |
| 0.6-0.7 | 2 | 0.637 | 0.500 |
| 0.7-0.8 | 4 | 0.751 | 0.500 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.374 | 0.250 |
| 0.4-0.5 | 12 | 0.455 | 0.500 |
| 0.5-0.6 | 4 | 0.558 | 0.250 |
| 0.6-0.7 | 4 | 0.626 | 0.750 |
| 0.7-0.8 | 4 | 0.762 | 0.500 |
| 0.8-0.9 | 2 | 0.838 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 5 | 0.385 | 0.200 |
| 0.4-0.5 | 10 | 0.442 | 0.400 |
| 0.5-0.6 | 4 | 0.560 | 1.000 |
| 0.6-0.7 | 6 | 0.649 | 0.333 |
| 0.7-0.8 | 2 | 0.752 | 0.500 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 6 | 0.390 | 0.333 |
| 0.4-0.5 | 10 | 0.446 | 0.500 |
| 0.5-0.6 | 10 | 0.556 | 0.400 |
| 0.6-0.7 | 9 | 0.625 | 0.889 |
| 0.7-0.8 | 3 | 0.743 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.368 | 0.000 |
| 0.4-0.5 | 8 | 0.443 | 0.500 |
| 0.5-0.6 | 8 | 0.555 | 0.250 |
| 0.6-0.7 | 6 | 0.641 | 1.000 |
| 0.7-0.8 | 4 | 0.737 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0416 vs walk-forward 0.9990 (delta +0.0426, n=30) — ok.
- laliga: ledger 0.9774 vs walk-forward 0.9903 (delta -0.0129, n=30) — ok.
- bundesliga: ledger 1.0647 vs walk-forward 1.0083 (delta +0.0564, n=27) — DECAY FLAG.
- seriea: ledger 0.9511 vs walk-forward 1.0030 (delta -0.0519, n=38) — ok.
- ligue1: ledger 0.8551 vs walk-forward 1.0263 (delta -0.1713, n=27) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._