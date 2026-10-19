# Weekly AI forecast memo — 2026-10-18

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-18 | 1.0032 | 1.0344 (xgb_tiny) | 1.0014 | 1.0826 |
| laliga | v2026-10-18 | 1.0149 | 1.0273 (xgb_tiny) | 0.9915 | 1.0663 |
| bundesliga | v2026-10-18 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-10-18 | 1.0081 | 1.0416 (xgb_tiny) | 1.0055 | 1.0932 |
| ligue1 | v2026-10-18 | 1.0725 | 1.0510 (xgb_tiny) | 1.0264 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 19 | 1.0917 | 1.0852 | 1.0530 |
| laliga | 18 | 0.9045 | 1.0397 | 0.9534 |
| bundesliga | 18 | 1.0300 | 1.1561 | 1.0865 |
| seriea | 18 | 0.9167 | 1.1618 | 1.0114 |
| ligue1 | 18 | 0.7882 | 0.9857 | 0.8333 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 6 | 0.378 | 0.667 |
| 0.4-0.5 | 5 | 0.448 | 0.400 |
| 0.5-0.6 | 5 | 0.555 | 0.400 |
| 0.6-0.7 | 1 | 0.628 | 0.000 |
| 0.7-0.8 | 1 | 0.749 | 1.000 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.367 | 0.333 |
| 0.4-0.5 | 7 | 0.450 | 0.286 |
| 0.5-0.6 | 1 | 0.576 | 0.000 |
| 0.6-0.7 | 2 | 0.634 | 0.500 |
| 0.7-0.8 | 3 | 0.776 | 0.667 |
| 0.8-0.9 | 2 | 0.838 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.391 | 0.000 |
| 0.4-0.5 | 6 | 0.434 | 0.333 |
| 0.5-0.6 | 3 | 0.548 | 1.000 |
| 0.6-0.7 | 4 | 0.645 | 0.250 |
| 0.7-0.8 | 2 | 0.752 | 0.500 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.392 | 0.250 |
| 0.4-0.5 | 3 | 0.433 | 0.333 |
| 0.5-0.6 | 6 | 0.551 | 0.500 |
| 0.6-0.7 | 4 | 0.620 | 0.750 |
| 0.7-0.8 | 1 | 0.783 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.368 | 0.000 |
| 0.4-0.5 | 4 | 0.447 | 0.750 |
| 0.5-0.6 | 6 | 0.556 | 0.167 |
| 0.6-0.7 | 4 | 0.626 | 1.000 |
| 0.7-0.8 | 3 | 0.734 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0530 vs walk-forward 1.0014 (delta +0.0516, n=19) — DECAY FLAG.
- laliga: ledger 0.9534 vs walk-forward 0.9915 (delta -0.0382, n=18) — ok.
- bundesliga: ledger 1.0865 vs walk-forward 1.0083 (delta +0.0782, n=18) — DECAY FLAG.
- seriea: ledger 1.0114 vs walk-forward 1.0055 (delta +0.0059, n=18) — ok.
- ligue1: ledger 0.8333 vs walk-forward 1.0264 (delta -0.1931, n=18) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._