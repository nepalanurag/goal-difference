# Weekly AI forecast memo — 2026-11-25

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-25 | 0.9950 | 1.0120 (xgb_tiny) | 0.9739 | 1.0674 |
| laliga | v2026-11-25 | 1.0041 | 1.0238 (xgb_tiny) | 0.9956 | 1.0687 |
| bundesliga | v2026-11-25 | 1.0149 | 1.0273 (xgb_tiny) | 1.0018 | 1.0733 |
| seriea | v2026-11-25 | 1.0008 | 1.0081 (xgb_tiny) | 0.9774 | 1.0810 |
| ligue1 | v2026-11-25 | 1.0147 | 1.0534 (xgb_tiny) | 1.0114 | 1.0745 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 0 | n/a | n/a | n/a |
| laliga | 0 | n/a | n/a | n/a |
| bundesliga | 0 | n/a | n/a | n/a |
| seriea | 0 | n/a | n/a | n/a |
| ligue1 | 0 | n/a | n/a | n/a |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 17 | 0.370 | 0.529 |
| 0.4-0.5 | 17 | 0.445 | 0.588 |
| 0.5-0.6 | 13 | 0.558 | 0.385 |
| 0.6-0.7 | 5 | 0.648 | 0.400 |
| 0.7-0.8 | 6 | 0.749 | 0.500 |
| 0.8-0.9 | 2 | 0.824 | 0.500 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 9 | 0.379 | 0.222 |
| 0.4-0.5 | 25 | 0.455 | 0.440 |
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
| 0.4-0.5 | 20 | 0.450 | 0.500 |
| 0.5-0.6 | 21 | 0.556 | 0.571 |
| 0.6-0.7 | 14 | 0.628 | 0.857 |
| 0.7-0.8 | 6 | 0.724 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.374 | 0.250 |
| 0.4-0.5 | 18 | 0.450 | 0.500 |
| 0.5-0.6 | 12 | 0.547 | 0.250 |
| 0.6-0.7 | 12 | 0.657 | 0.833 |
| 0.7-0.8 | 8 | 0.729 | 0.875 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0866 vs walk-forward 0.9739 (delta +0.1127, n=60) — DECAY FLAG.
- laliga: ledger 0.9717 vs walk-forward 0.9956 (delta -0.0239, n=60) — ok.
- bundesliga: ledger 1.0519 vs walk-forward 1.0018 (delta +0.0502, n=54) — DECAY FLAG.
- seriea: ledger 0.9071 vs walk-forward 0.9774 (delta -0.0703, n=70) — ok.
- ligue1: ledger 0.9290 vs walk-forward 1.0114 (delta -0.0825, n=54) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._