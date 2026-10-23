# Weekly AI forecast memo — 2026-10-23

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-23 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-10-23 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-10-23 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-10-23 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-10-23 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 20 | 1.0826 | 1.0883 | 1.0514 |
| laliga | 20 | 0.9109 | 1.0951 | 0.9772 |
| bundesliga | 18 | 1.0300 | 1.1561 | 1.0865 |
| seriea | 20 | 0.9367 | 1.2100 | 1.0501 |
| ligue1 | 18 | 0.7882 | 0.9857 | 0.8333 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 7 | 0.375 | 0.714 |
| 0.4-0.5 | 5 | 0.448 | 0.400 |
| 0.5-0.6 | 5 | 0.555 | 0.400 |
| 0.6-0.7 | 1 | 0.628 | 0.000 |
| 0.7-0.8 | 1 | 0.749 | 1.000 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 3 | 0.367 | 0.333 |
| 0.4-0.5 | 8 | 0.445 | 0.375 |
| 0.5-0.6 | 2 | 0.588 | 0.000 |
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
| 0.4-0.5 | 5 | 0.444 | 0.200 |
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

- pl: ledger 1.0514 vs walk-forward 0.9990 (delta +0.0524, n=20) — DECAY FLAG.
- laliga: ledger 0.9772 vs walk-forward 0.9903 (delta -0.0131, n=20) — ok.
- bundesliga: ledger 1.0865 vs walk-forward 1.0083 (delta +0.0782, n=18) — DECAY FLAG.
- seriea: ledger 1.0501 vs walk-forward 1.0030 (delta +0.0471, n=20) — ok.
- ligue1: ledger 0.8333 vs walk-forward 1.0263 (delta -0.1930, n=18) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._