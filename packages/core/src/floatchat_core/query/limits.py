"""Bounded query limits (plan section 4.4, PRD sections 3.1 and 16.4); environment-overridable."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QueryLimits(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUERY_", env_file=None, extra="ignore")

    request_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    time_span_days: int = Field(default=366, ge=1, le=3660)
    page_size: int = Field(default=1000, ge=1, le=10000)
    default_page_size: int = Field(default=100, ge=1, le=10000)
    max_rows: int = Field(default=50_000, ge=1, le=1_000_000)
    response_bytes: int = Field(default=8 * 1024 * 1024, ge=65536, le=256 * 1024 * 1024)
    postgres_level_budget: int = Field(default=1_000_000, ge=1, le=10**9)
    duckdb_level_budget: int = Field(default=5_000_000, ge=1, le=10**9)
    object_fetch_bytes: int = Field(default=512 * 1024 * 1024, ge=1, le=16 * 1024**3)
    nearest_radius_km: float = Field(default=2000.0, gt=0, le=20_000)
    nearest_k: int = Field(default=100, ge=1, le=10_000)
    chart_points_per_series: int = Field(default=5000, ge=1, le=1_000_000)
    chart_series: int = Field(default=20, ge=1, le=1000)
    query_timeout_seconds: float = Field(default=10.0, gt=0, le=600)
    duckdb_memory_mib: int = Field(default=512, ge=64, le=65536)
    duckdb_threads: int = Field(default=2, ge=1, le=64)
    object_cache_bytes: int = Field(default=2 * 1024**3, ge=1024 * 1024, le=1024**4)
    histogram_bins: int = Field(default=200, ge=1, le=10_000)
    trajectory_points: int = Field(default=1000, ge=1, le=100_000)
    profile_levels: int = Field(default=10_000, ge=1, le=10_000)

    def public(self) -> dict[str, float | int]:
        """The limits a client may rely on, as published by the parameter catalogue."""
        return {
            "request_bytes": self.request_bytes,
            "time_span_days": self.time_span_days,
            "page_size": self.page_size,
            "default_page_size": self.default_page_size,
            "max_rows": self.max_rows,
            "response_bytes": self.response_bytes,
            "postgres_level_budget": self.postgres_level_budget,
            "duckdb_level_budget": self.duckdb_level_budget,
            "nearest_radius_km": self.nearest_radius_km,
            "nearest_k": self.nearest_k,
            "chart_points_per_series": self.chart_points_per_series,
            "chart_series": self.chart_series,
            "query_timeout_seconds": self.query_timeout_seconds,
            "histogram_bins": self.histogram_bins,
            "trajectory_points": self.trajectory_points,
            "profile_levels": self.profile_levels,
        }
