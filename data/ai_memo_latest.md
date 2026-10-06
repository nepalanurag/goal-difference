# Weekly AI forecast memo — 2026-10-06

> AI-generated. All numbers below come from the fitted models and
> real fixture results; nothing here was invented by the AI.

## 1. Walk-forward log-loss (fitted models)

| league | model version | poisson | ML (chosen) | ensemble | baseline |
| --- | --- | --- | --- | --- | --- |
| pl | v2026-10-06 | 0.9316 | 0.9436 (xgb_tiny) | 0.9157 | 1.0849 |
| laliga | v2026-10-06 | 0.8947 | 0.9315 (xgb_reg) | 0.8962 | 1.0661 |
| bundesliga | v2026-10-06 | 0.9306 | 0.9314 (xgb_reg) | 0.9002 | 1.0825 |
| seriea | v2026-10-06 | 0.9351 | 0.9565 (xgb_reg) | 0.9266 | 1.0942 |
| ligue1 | v2026-10-06 | 0.9212 | 0.9409 (xgb_reg) | 0.9062 | 1.0728 |

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
No scored fixtures yet.

### laliga
No scored fixtures yet.

### bundesliga
No scored fixtures yet.

### seriea
No scored fixtures yet.

### ligue1
No scored fixtures yet.

## 4. Model-decay watch

Compares the ledger's overall ensemble log-loss against the walk-forward ensemble log-loss. Flagged when the ledger is worse by more than 0.05.

- pl: not enough scored data yet.
- laliga: not enough scored data yet.
- bundesliga: not enough scored data yet.
- seriea: not enough scored data yet.
- ligue1: not enough scored data yet.

---
_Produced by etl.ai_forecaster — AI as the extra layer over the fitted statistical and ML models._