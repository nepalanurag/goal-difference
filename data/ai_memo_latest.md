# Weekly AI forecast memo — 2026-10-11

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-11 | 1.0118 | 0.9430 (xgb_tiny) | 0.9396 | 1.0849 |
| laliga | v2026-10-11 | 1.0308 | 0.9364 (xgb_reg) | 0.9368 | 1.0661 |
| bundesliga | v2026-10-11 | 1.0663 | 0.9255 (xgb_tiny) | 0.9347 | 1.0824 |
| seriea | v2026-10-11 | 1.0342 | 0.9533 (xgb_reg) | 0.9514 | 1.0943 |
| ligue1 | v2026-10-11 | 1.0766 | 0.9303 (xgb_reg) | 0.9457 | 1.0728 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 9 | 1.0915 | 1.0289 | 1.0455 |
| laliga | 8 | 0.8433 | 0.7367 | 0.7645 |
| bundesliga | 9 | 1.1937 | 1.3403 | 1.2621 |
| seriea | 8 | 0.9049 | 0.9091 | 0.8608 |
| ligue1 | 9 | 0.6629 | 0.8972 | 0.7560 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.381 | 0.667 |
| 0.4-0.5 | 2 | 0.443 | 0.500 |
| 0.5-0.6 | 3 | 0.565 | 0.333 |
| 0.7-0.8 | 1 | 0.749 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 2 | 0.376 | 0.500 |
| 0.4-0.5 | 3 | 0.427 | 0.000 |
| 0.7-0.8 | 2 | 0.766 | 1.000 |
| 0.8-0.9 | 1 | 0.868 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.397 | 0.000 |
| 0.4-0.5 | 3 | 0.431 | 0.000 |
| 0.5-0.6 | 2 | 0.532 | 1.000 |
| 0.6-0.7 | 2 | 0.634 | 0.000 |
| 0.7-0.8 | 1 | 0.747 | 0.000 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.397 | 1.000 |
| 0.4-0.5 | 2 | 0.432 | 0.000 |
| 0.5-0.6 | 3 | 0.551 | 0.667 |
| 0.6-0.7 | 1 | 0.629 | 1.000 |
| 0.7-0.8 | 1 | 0.783 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.4-0.5 | 3 | 0.457 | 1.000 |
| 0.5-0.6 | 3 | 0.584 | 0.333 |
| 0.6-0.7 | 1 | 0.633 | 1.000 |
| 0.7-0.8 | 2 | 0.723 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0455 vs walk-forward 0.9396 (delta +0.1059, n=9) — DECAY FLAG.
- laliga: ledger 0.7645 vs walk-forward 0.9368 (delta -0.1723, n=8) — ok.
- bundesliga: ledger 1.2621 vs walk-forward 0.9347 (delta +0.3274, n=9) — DECAY FLAG.
- seriea: ledger 0.8608 vs walk-forward 0.9514 (delta -0.0906, n=8) — ok.
- ligue1: ledger 0.7560 vs walk-forward 0.9457 (delta -0.1897, n=9) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._