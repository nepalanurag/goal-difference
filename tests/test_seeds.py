"""Phase 9.5: reproducibility seeds are recorded config, not folklore.

The simulation seed lives in etl/config.py (simulation_seed=42) and is
threaded through fit.py (model run records) and simulate.py
(np.random.default_rng(settings.simulation_seed)). This test pins it so an
accidental edit is caught by CI.
"""
from etl.config import settings


def test_simulation_seed_is_42():
    assert settings.simulation_seed == 42
