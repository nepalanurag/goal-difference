# Weekly AI forecast memo — 2026-11-09

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-09 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-11-09 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-11-09 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-11-09 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-11-09 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 50 | 1.0805 | 1.1569 | 1.0896 |
| laliga | 50 | 0.9110 | 1.0847 | 0.9766 |
| bundesliga | 45 | 0.9796 | 1.1657 | 1.0397 |
| seriea | 60 | 0.8757 | 1.0315 | 0.9327 |
| ligue1 | 45 | 0.8919 | 0.9065 | 0.8556 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 14 | 0.370 | 0.500 |
| 0.4-0.5 | 14 | 0.447 | 0.571 |
| 0.5-0.6 | 11 | 0.559 | 0.273 |
| 0.6-0.7 | 4 | 0.647 | 0.500 |
| 0.7-0.8 | 6 | 0.749 | 0.500 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.377 | 0.250 |
| 0.4-0.5 | 18 | 0.456 | 0.389 |
| 0.5-0.6 | 8 | 0.539 | 0.625 |
| 0.6-0.7 | 8 | 0.635 | 0.750 |
| 0.7-0.8 | 5 | 0.769 | 0.400 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.388 | 0.250 |
| 0.4-0.5 | 19 | 0.452 | 0.368 |
| 0.5-0.6 | 7 | 0.558 | 0.857 |
| 0.6-0.7 | 8 | 0.642 | 0.375 |
| 0.7-0.8 | 3 | 0.750 | 0.667 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.382 | 0.444 |
| 0.4-0.5 | 18 | 0.450 | 0.556 |
| 0.5-0.6 | 16 | 0.558 | 0.500 |
| 0.6-0.7 | 12 | 0.625 | 0.833 |
| 0.7-0.8 | 5 | 0.729 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.377 | 0.333 |
| 0.4-0.5 | 15 | 0.450 | 0.467 |
| 0.5-0.6 | 10 | 0.554 | 0.200 |
| 0.6-0.7 | 10 | 0.651 | 1.000 |
| 0.7-0.8 | 7 | 0.733 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0896 vs walk-forward 0.9990 (delta +0.0906, n=50) — DECAY FLAG.
- laliga: ledger 0.9766 vs walk-forward 0.9903 (delta -0.0138, n=50) — ok.
- bundesliga: ledger 1.0397 vs walk-forward 1.0083 (delta +0.0314, n=45) — ok.
- seriea: ledger 0.9327 vs walk-forward 1.0030 (delta -0.0703, n=60) — ok.
- ligue1: ledger 0.8556 vs walk-forward 1.0263 (delta -0.1707, n=45) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._