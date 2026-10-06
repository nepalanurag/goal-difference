"""Central configuration for the goal-difference ETL.

All knobs live here (pydantic-settings): environment variables prefixed with
``GOALDIFF_`` override the defaults, so CI and local runs behave the same way.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOALDIFF_", extra="ignore")

    repo_root: Path = Field(default=REPO_ROOT)
    data_dir: Path = Field(default=REPO_ROOT / "data")
    raw_dir: Path = Field(default=REPO_ROOT / "data" / "raw")
    docs_dir: Path = Field(default=REPO_ROOT / "docs")

    # League registry: api-football id, football-data.co.uk CSV code, team count.
    leagues: Dict[str, Dict[str, object]] = Field(
        default={
            "pl": {"name": "Premier League", "api_id": 39, "csv_code": "E0", "n_teams": 20},
            "laliga": {"name": "LaLiga", "api_id": 140, "csv_code": "SP1", "n_teams": 20},
            "bundesliga": {"name": "Bundesliga", "api_id": 78, "csv_code": "D1", "n_teams": 18},
            "seriea": {"name": "Serie A", "api_id": 135, "csv_code": "I1", "n_teams": 20},
            "ligue1": {"name": "Ligue 1", "api_id": 61, "csv_code": "F1", "n_teams": 18},
        }
    )
    league_order: List[str] = Field(default=["pl", "laliga", "bundesliga", "seriea", "ligue1"])

    # Seasons we model on. "2023" means 2023/24.
    historical_seasons: List[str] = Field(default=["2023", "2024"])
    csv_only_season: str = Field(default="2025")  # 2025/26: api-football free tier blocks it
    live_season: str = Field(default="2026")  # 2026/27: FPL (PL) + current CSVs

    # Feature / model knobs.
    form_window: int = Field(default=5)
    recency_half_life_days: float = Field(default=180.0)
    simulation_runs: int = Field(default=10_000)
    simulation_seed: int = Field(default=42)
    walkforward_splits: int = Field(default=5)

    # api-football politeness.
    api_sleep_seconds: float = Field(default=7.0)

    log_level: str = Field(default="INFO")


settings = Settings()
