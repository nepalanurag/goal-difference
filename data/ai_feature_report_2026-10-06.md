# AI feature ideation report — pl — 2026-10-06

> AI-generated. The agent proposes, the human vets: no candidate is
> enabled by default, and nothing below changes the fitted models
> until a human approves it.

Protocol: short time-respecting walk-forward (2 splits) of the Poisson model only. Delta log-loss = candidate minus baseline (negative = better). All candidate inputs are shift(1)-lagged, so there is no leakage.

Baseline Poisson log-loss (2 splits): 0.9491

| candidate | hypothesis | delta log-loss | verdict |
| --- | --- | --- | --- |
| rest_days_sq | Fatigue is nonlinear: 2 days of rest hurts far more than a linear extrapolation from 5-vs-7 days implies. Squaring rest days lets the Poisson regressions see that curvature. | -0.00020 | needs-human-review |
| shot_quality_diff | On-target share of shots is a shot-based stand-in for chance quality (we label it shot-based, never true xG). A team converting a higher share of shots on target should outscore its raw shot volume. | +0.00733 | kill |
| momentum_differential | Relative trajectory carries signal beyond absolute ratings: an improving side against a fading one is worth more than the two ratings alone suggest. | +0.00008 | needs-human-review |
| venue_strength_asymmetry | Home advantage interacts with how venue-dependent each team is. A strong home team hosting a poor traveler is a bigger edge than venue splits already capture independently. | -0.00010 | needs-human-review |
| euro_congestion_delta | It is the congestion GAP that matters: a side that played in Europe 3 days ago against a rested opponent faces rotation risk the absolute midweek flags miss. | +0.00000 | needs-human-review |

## Flag state

All candidates remain disabled by default:
- rest_days_sq: enabled = False
- shot_quality_diff: enabled = False
- momentum_differential: enabled = False
- venue_strength_asymmetry: enabled = False
- euro_congestion_delta: enabled = False

---
_Produced by etl.ai_features — proposals only, human vets._