# Weekly AI forecast memo — 2026-11-07

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-11-07 | 1.0028 | 1.0310 (xgb_tiny) | 0.9990 | 1.0826 |
| laliga | v2026-11-07 | 0.9933 | 1.0300 (xgb_tiny) | 0.9903 | 1.0661 |
| bundesliga | v2026-11-07 | 1.0496 | 1.0358 (xgb_reg) | 1.0083 | 1.0822 |
| seriea | v2026-11-07 | 1.0030 | 1.0405 (xgb_tiny) | 1.0030 | 1.0941 |
| ligue1 | v2026-11-07 | 1.0725 | 1.0510 (xgb_tiny) | 1.0263 | 1.0712 |

## 2. Ledger scoring this run

| league | newly scored | logloss poisson | logloss ML | logloss ensemble |
| --- | --- | --- | --- | --- |
| pl | 44 | 1.1078 | 1.1585 | 1.1050 |
| laliga | 43 | 0.9130 | 1.1230 | 1.0003 |
| bundesliga | 41 | 1.0178 | 1.1628 | 1.0580 |
| seriea | 53 | 0.8835 | 1.0710 | 0.9590 |
| ligue1 | 37 | 0.8595 | 0.8431 | 0.8036 |

## 3. Calibration (all scored fixtures)

### pl
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 13 | 0.371 | 0.462 |
| 0.4-0.5 | 13 | 0.443 | 0.538 |
| 0.5-0.6 | 10 | 0.560 | 0.300 |
| 0.6-0.7 | 3 | 0.657 | 0.333 |
| 0.7-0.8 | 4 | 0.751 | 0.500 |
| 0.8-0.9 | 1 | 0.843 | 1.000 |

### laliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.377 | 0.250 |
| 0.4-0.5 | 15 | 0.457 | 0.467 |
| 0.5-0.6 | 7 | 0.545 | 0.571 |
| 0.6-0.7 | 5 | 0.632 | 0.600 |
| 0.7-0.8 | 5 | 0.769 | 0.400 |
| 0.8-0.9 | 3 | 0.846 | 1.000 |

### bundesliga
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.388 | 0.250 |
| 0.4-0.5 | 17 | 0.450 | 0.412 |
| 0.5-0.6 | 6 | 0.565 | 0.833 |
| 0.6-0.7 | 7 | 0.647 | 0.286 |
| 0.7-0.8 | 3 | 0.750 | 0.667 |

### seriea
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 8 | 0.385 | 0.500 |
| 0.4-0.5 | 15 | 0.444 | 0.533 |
| 0.5-0.6 | 15 | 0.557 | 0.467 |
| 0.6-0.7 | 11 | 0.622 | 0.818 |
| 0.7-0.8 | 4 | 0.735 | 1.000 |

### ligue1
| band | n | mean P(predicted outcome) | hit rate |
| --- | --- | --- | --- |
| 0.3-0.4 | 2 | 0.377 | 0.000 |
| 0.4-0.5 | 11 | 0.445 | 0.455 |
| 0.5-0.6 | 8 | 0.555 | 0.250 |
| 0.6-0.7 | 9 | 0.647 | 1.000 |
| 0.7-0.8 | 7 | 0.733 | 1.000 |

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: ledger 1.1050 vs walk-forward 0.9990 (delta +0.1059, n=44) — DECAY FLAG.
- laliga: ledger 1.0003 vs walk-forward 0.9903 (delta +0.0100, n=43) — ok.
- bundesliga: ledger 1.0580 vs walk-forward 1.0083 (delta +0.0497, n=41) — ok.
- seriea: ledger 0.9590 vs walk-forward 1.0030 (delta -0.0440, n=53) — ok.
- ligue1: ledger 0.8036 vs walk-forward 1.0263 (delta -0.2228, n=37) — ok.

One or more leagues are flagged. The weekly memo should investigate before the next refresh: check for distribution shift (new season, promoted teams) or stale features.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._