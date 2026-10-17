# Weekly AI forecast memo — 2026-10-17

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-17 | 1.0118 | 0.9430 (xgb_tiny) | 0.9396 | 1.0849 |
| laliga | v2026-10-17 | 1.0308 | 0.9364 (xgb_reg) | 0.9368 | 1.0661 |
| bundesliga | v2026-10-17 | 1.0663 | 0.9255 (xgb_tiny) | 0.9347 | 1.0824 |
| seriea | v2026-10-17 | 1.0342 | 0.9533 (xgb_reg) | 0.9514 | 1.0943 |
| ligue1 | v2026-10-17 | 1.0766 | 0.9303 (xgb_reg) | 0.9457 | 1.0728 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 11 | 1.1280 | 1.0163 | 1.0573 |
| laliga | 12 | 1.0327 | 1.0306 | 1.0091 |
| bundesliga | 15 | 1.1134 | 1.2639 | 1.1809 |
| seriea | 12 | 0.9172 | 0.9701 | 0.9159 |
| ligue1 | 10 | 0.7343 | 0.9396 | 0.8147 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.383 | 0.750 |
| 0.4-0.5 | 3 | 0.429 | 0.333 |
| 0.5-0.6 | 3 | 0.565 | 0.333 |
| 0.7-0.8 | 1 | 0.749 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 2 | 0.376 | 0.500 |
| 0.4-0.5 | 5 | 0.448 | 0.000 |
| 0.6-0.7 | 1 | 0.632 | 0.000 |
| 0.7-0.8 | 3 | 0.776 | 0.667 |
| 0.8-0.9 | 1 | 0.868 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 2 | 0.394 | 0.000 |
| 0.4-0.5 | 6 | 0.434 | 0.333 |
| 0.5-0.6 | 3 | 0.548 | 1.000 |
| 0.6-0.7 | 3 | 0.633 | 0.000 |
| 0.7-0.8 | 1 | 0.747 | 0.000 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.397 | 1.000 |
| 0.4-0.5 | 3 | 0.433 | 0.333 |
| 0.5-0.6 | 5 | 0.558 | 0.600 |
| 0.6-0.7 | 2 | 0.639 | 1.000 |
| 0.7-0.8 | 1 | 0.783 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.4-0.5 | 4 | 0.447 | 0.750 |
| 0.5-0.6 | 3 | 0.584 | 0.333 |
| 0.6-0.7 | 1 | 0.633 | 1.000 |
| 0.7-0.8 | 2 | 0.723 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0573 vs walk-forward 0.9396 (delta +0.1177, n=11) — DECAY FLAG.
- laliga: ledger 1.0091 vs walk-forward 0.9368 (delta +0.0723, n=12) — DECAY FLAG.
- bundesliga: ledger 1.1809 vs walk-forward 0.9347 (delta +0.2462, n=15) — DECAY FLAG.
- seriea: ledger 0.9159 vs walk-forward 0.9514 (delta -0.0356, n=12) — ok.
- ligue1: ledger 0.8147 vs walk-forward 0.9457 (delta -0.1309, n=10) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._