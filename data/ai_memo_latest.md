# Weekly AI forecast memo — 2026-11-28

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-28 | 0.9950 | 1.0120 (xgb_tiny) | 0.9739 | 1.0674 |
| laliga | v2026-11-28 | 1.0041 | 1.0238 (xgb_tiny) | 0.9956 | 1.0687 |
| bundesliga | v2026-11-28 | 1.0149 | 1.0273 (xgb_tiny) | 1.0018 | 1.0733 |
| seriea | v2026-11-28 | 1.0008 | 1.0081 (xgb_tiny) | 0.9774 | 1.0810 |
| ligue1 | v2026-11-28 | 1.0147 | 1.0534 (xgb_tiny) | 1.0114 | 1.0745 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 4 | 1.1706 | 1.2212 | 1.1879 |
| laliga | 3 | 1.0658 | 1.2177 | 1.1263 |
| bundesliga | 5 | 1.3672 | 1.4167 | 1.3041 |
| seriea | 2 | 0.6484 | 0.6079 | 0.6234 |
| ligue1 | 2 | 0.4971 | 0.5881 | 0.5044 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 19 | 0.370 | 0.526 |
| 0.4-0.5 | 18 | 0.445 | 0.611 |
| 0.5-0.6 | 14 | 0.558 | 0.357 |
| 0.6-0.7 | 5 | 0.648 | 0.400 |
| 0.7-0.8 | 6 | 0.749 | 0.500 |
| 0.8-0.9 | 2 | 0.824 | 0.500 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.379 | 0.222 |
| 0.4-0.5 | 26 | 0.454 | 0.462 |
| 0.5-0.6 | 9 | 0.535 | 0.556 |
| 0.6-0.7 | 10 | 0.636 | 0.700 |
| 0.7-0.8 | 7 | 0.762 | 0.571 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.387 | 0.222 |
| 0.4-0.5 | 25 | 0.450 | 0.440 |
| 0.5-0.6 | 11 | 0.543 | 0.545 |
| 0.6-0.7 | 11 | 0.638 | 0.455 |
| 0.7-0.8 | 3 | 0.750 | 0.667 |
| 0.8-0.9 | 1 | 0.827 | 0.000 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.382 | 0.444 |
| 0.4-0.5 | 21 | 0.450 | 0.524 |
| 0.5-0.6 | 21 | 0.556 | 0.571 |
| 0.6-0.7 | 15 | 0.627 | 0.867 |
| 0.7-0.8 | 7 | 0.722 | 0.857 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.374 | 0.250 |
| 0.4-0.5 | 18 | 0.450 | 0.500 |
| 0.5-0.6 | 14 | 0.552 | 0.286 |
| 0.6-0.7 | 13 | 0.656 | 0.846 |
| 0.7-0.8 | 8 | 0.729 | 0.875 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0930 vs walk-forward 0.9739 (delta +0.1190, n=64) — DECAY FLAG.
- laliga: ledger 0.9882 vs walk-forward 0.9956 (delta -0.0074, n=64) — ok.
- bundesliga: ledger 1.0751 vs walk-forward 1.0018 (delta +0.0733, n=60) — DECAY FLAG.
- seriea: ledger 0.9111 vs walk-forward 0.9774 (delta -0.0663, n=73) — ok.
- ligue1: ledger 0.9234 vs walk-forward 1.0114 (delta -0.0881, n=57) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._