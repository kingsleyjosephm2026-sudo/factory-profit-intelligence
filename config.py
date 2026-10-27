"""Runtime configuration. Every value can be overridden with an FPI_* environment variable."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FPI_", extra="ignore")

    # --- infrastructure ---
    database_url: str = "sqlite:///./fpi_dev.db"  # PostgreSQL: postgresql+psycopg://user:pass@host/db
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    max_upload_mb: int = 5
    max_upload_rows: int = 100_000
    seed: int = 42
    demo_days: int = 90

    # --- business / loss-model assumptions (documented in ANALYTICS_METHODOLOGY.md) ---
    currency: str = "INR"
    downtime_unrecoverable_share: float = 0.70  # share of downtime-lost output that cannot be recovered
    scrap_salvage_rate: float = 0.10  # share of input cost recovered from defective units
    energy_tolerance_pct: float = 5.0  # kWh/unit above baseline tolerated before it counts as "excess"
    material_allowance_pct: float = 1.0  # standard material-waste allowance
    carrying_rate_annual: float = 0.18  # inventory carrying cost, fraction of stock value per year
    max_days_cover: float = 45.0  # stock above this many days of usage is "excess"
    slow_moving_days_cover: float = 90.0
    benchmark_unplanned_downtime_pct: float = 5.0
    benchmark_defect_rate_pct: float = 2.0
    energy_avoidable_share: float = 0.60
    material_avoidable_share: float = 0.50
    realization_factor: float = 0.50  # share of avoidable cost assumed capturable (potential savings)
    target_efficiency: float = 0.85  # production target = ideal output x this factor

    # --- live demo simulation ---
    sim_interval_seconds: float = 5.0
    sim_interval_minutes: int = 15  # simulated minutes advanced per tick
    sim_max_rows: int = 3000  # retention cap for simulated production rows
    sim_autostart: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
