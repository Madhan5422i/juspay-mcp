from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def is_local_development() -> bool:
    raw = os.getenv("DEPLOYMENT_ENV") or ""
    return raw.strip().lower() == "local"


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool
    database_url: str | None
    session_gap_minutes: int
    event_max_bytes: int
    pool_min_size: int
    pool_max_size: int


def load() -> AnalyticsConfig:
    database_url = os.getenv("ANALYTICS_DATABASE_URL")
    enabled = _env_bool("ANALYTICS_ENABLED", bool(database_url))
    return AnalyticsConfig(
        enabled=enabled,
        database_url=database_url if database_url else None,
        session_gap_minutes=_env_int("ANALYTICS_SESSION_GAP_MINUTES", 60),
        event_max_bytes=_env_int("ANALYTICS_EVENT_MAX_BYTES", 32 * 1024),
        pool_min_size=_env_int("ANALYTICS_POOL_MIN_SIZE", 1),
        pool_max_size=_env_int("ANALYTICS_POOL_MAX_SIZE", 5),
    )
