# Weekly AI forecast memo — 2026-10-24

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-24 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-10-24 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-10-24 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-10-24 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-10-24 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 24 | 1.0532 | 1.0651 | 1.0295 |
| laliga | 23 | 0.9523 | 1.1201 | 1.0081 |
| bundesliga | 24 | 1.0894 | 1.1489 | 1.1005 |
| seriea | 23 | 0.8995 | 1.1381 | 0.9925 |
| ligue1 | 19 | 0.8168 | 1.0150 | 0.8659 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.372 | 0.625 |
| 0.4-0.5 | 5 | 0.448 | 0.400 |
| 0.5-0.6 | 6 | 0.559 | 0.500 |
| 0.6-0.7 | 1 | 0.628 | 0.000 |
| 0.7-0.8 | 3 | 0.742 | 0.667 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.367 | 0.333 |
| 0.4-0.5 | 10 | 0.451 | 0.400 |
| 0.5-0.6 | 3 | 0.567 | 0.000 |
| 0.6-0.7 | 2 | 0.634 | 0.500 |
| 0.7-0.8 | 3 | 0.776 | 0.667 |
| 0.8-0.9 | 2 | 0.838 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 5 | 0.385 | 0.200 |
| 0.4-0.5 | 9 | 0.440 | 0.444 |
| 0.5-0.6 | 3 | 0.548 | 1.000 |
| 0.6-0.7 | 5 | 0.652 | 0.200 |
| 0.7-0.8 | 2 | 0.752 | 0.500 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 4 | 0.392 | 0.250 |
| 0.4-0.5 | 6 | 0.444 | 0.333 |
| 0.5-0.6 | 7 | 0.552 | 0.571 |
| 0.6-0.7 | 5 | 0.626 | 0.800 |
| 0.7-0.8 | 1 | 0.783 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 1 | 0.368 | 0.000 |
| 0.4-0.5 | 5 | 0.449 | 0.600 |
| 0.5-0.6 | 6 | 0.556 | 0.167 |
| 0.6-0.7 | 4 | 0.626 | 1.000 |
| 0.7-0.8 | 3 | 0.734 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.0295 vs walk-forward 0.9990 (delta +0.0305, n=24) — ok.
- laliga: ledger 1.0081 vs walk-forward 0.9903 (delta +0.0178, n=23) — ok.
- bundesliga: ledger 1.1005 vs walk-forward 1.0083 (delta +0.0922, n=24) — DECAY FLAG.
- seriea: ledger 0.9925 vs walk-forward 1.0030 (delta -0.0105, n=23) — ok.
- ligue1: ledger 0.8659 vs walk-forward 1.0263 (delta -0.1604, n=19) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._