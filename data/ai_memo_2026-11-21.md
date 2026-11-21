# Weekly AI forecast memo — 2026-11-21

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-21 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-11-21 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-11-21 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-11-21 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-11-21 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 56 | 1.0893 | 1.1512 | 1.0923 |
| laliga | 54 | 0.9401 | 1.1197 | 1.0099 |
| bundesliga | 52 | 1.0112 | 1.1513 | 1.0458 |
| seriea | 63 | 0.8555 | 1.0070 | 0.9115 |
| ligue1 | 47 | 0.8928 | 0.9073 | 0.8584 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 16 | 0.371 | 0.500 |
| 0.4-0.5 | 14 | 0.447 | 0.571 |
| 0.5-0.6 | 13 | 0.558 | 0.385 |
| 0.6-0.7 | 5 | 0.648 | 0.400 |
| 0.7-0.8 | 6 | 0.749 | 0.500 |
| 0.8-0.9 | 2 | 0.824 | 0.500 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.379 | 0.222 |
| 0.4-0.5 | 21 | 0.456 | 0.333 |
| 0.5-0.6 | 8 | 0.539 | 0.625 |
| 0.6-0.7 | 8 | 0.635 | 0.750 |
| 0.7-0.8 | 5 | 0.769 | 0.400 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.388 | 0.250 |
| 0.4-0.5 | 23 | 0.450 | 0.435 |
| 0.5-0.6 | 7 | 0.558 | 0.857 |
| 0.6-0.7 | 10 | 0.637 | 0.500 |
| 0.7-0.8 | 3 | 0.750 | 0.667 |
| 0.8-0.9 | 1 | 0.827 | 0.000 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.382 | 0.444 |
| 0.4-0.5 | 18 | 0.450 | 0.556 |
| 0.5-0.6 | 17 | 0.559 | 0.529 |
| 0.6-0.7 | 14 | 0.628 | 0.857 |
| 0.7-0.8 | 5 | 0.729 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.377 | 0.333 |
| 0.4-0.5 | 16 | 0.450 | 0.438 |
| 0.5-0.6 | 11 | 0.551 | 0.273 |
| 0.6-0.7 | 10 | 0.651 | 1.000 |
| 0.7-0.8 | 7 | 0.733 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0923 vs walk-forward 0.9990 (delta +0.0932, n=56) — DECAY FLAG.
- laliga: ledger 1.0099 vs walk-forward 0.9903 (delta +0.0196, n=54) — ok.
- bundesliga: ledger 1.0458 vs walk-forward 1.0083 (delta +0.0375, n=52) — ok.
- seriea: ledger 0.9115 vs walk-forward 1.0030 (delta -0.0914, n=63) — ok.
- ligue1: ledger 0.8584 vs walk-forward 1.0263 (delta -0.1680, n=47) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._