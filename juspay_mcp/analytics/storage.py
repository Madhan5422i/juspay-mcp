from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import AnalyticsConfig, load

logger = logging.getLogger(__name__)

_cfg: AnalyticsConfig | None = None
_pool = None
_disabled_reason: str | None = None
_disabled_logged = False


def _config() -> AnalyticsConfig:
    global _cfg
    if _cfg is None:
        _cfg = load()
    return _cfg


def should_start_new_session(
    last_event_at: datetime | None,
    occurred_at: datetime,
    gap_minutes: int,
) -> bool:
    if last_event_at is None:
        return True
    return occurred_at - last_event_at > timedelta(minutes=gap_minutes)


async def _get_pool():
    global _pool, _disabled_reason, _disabled_logged

    cfg = _config()
    if not cfg.enabled:
        return None
    if not cfg.database_url:
        _disabled_reason = "ANALYTICS_DATABASE_URL/DATABASE_URL is not configured"
        if not _disabled_logged:
            logger.warning("Analytics disabled: %s", _disabled_reason)
            _disabled_logged = True
        return None
    if _disabled_reason:
        return None
    if _pool is not None:
        return _pool

    try:
        from psycopg_pool import AsyncConnectionPool
    except ImportError:
        _disabled_reason = (
            "psycopg_pool is unavailable; install psycopg[binary,pool] to enable analytics"
        )
        if not _disabled_logged:
            logger.warning("Analytics disabled: %s", _disabled_reason)
            _disabled_logged = True
        return None

    pool = AsyncConnectionPool(
        conninfo=cfg.database_url,
        min_size=cfg.pool_min_size,
        max_size=cfg.pool_max_size,
        open=False,
        kwargs={"autocommit": False},
    )
    await pool.open()
    _pool = pool
    logger.info("Analytics Postgres pool opened")
    return _pool


async def shutdown() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _assign_session(conn, install_id: str, occurred_at: datetime) -> uuid.UUID:
    cfg = _config()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select pg_advisory_xact_lock(hashtext(%s))
            """,
            (install_id,),
        )
        await cur.execute(
            """
            select inferred_session_id, occurred_at
            from analytics_events
            where install_id = %s
            order by occurred_at desc, id desc
            limit 1
            """,
            (install_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return uuid.uuid4()

        inferred_session_id, last_event_at = row
        if should_start_new_session(last_event_at, occurred_at, cfg.session_gap_minutes):
            return uuid.uuid4()
        return inferred_session_id


async def record_event(
    *,
    install_id: str,
    mid: str | None,
    event: dict[str, Any],
    occurred_at: datetime | None = None,
) -> uuid.UUID | None:
    timestamp = occurred_at or datetime.now(timezone.utc)
    try:
        pool = await _get_pool()
        if pool is None:
            return None

        async with pool.connection() as conn:
            async with conn.transaction():
                inferred_session_id = await _assign_session(conn, install_id, timestamp)
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        insert into analytics_events
                          (occurred_at, install_id, mid, inferred_session_id, event)
                        values (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            timestamp,
                            install_id,
                            mid,
                            inferred_session_id,
                            json.dumps(event, default=str),
                        ),
                    )
                return inferred_session_id
    except Exception:
        logger.exception("Failed to write analytics event")
        return None


async def fetch_integration_sessions(
    *,
    docs_and_dashboard_only: bool = True,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read inferred integration sessions for analytics dashboards."""
    try:
        pool = await _get_pool()
        if pool is None:
            return []

        safe_limit = max(1, min(limit, 1000))
        view_name = (
            "analytics_docs_dashboard_integration_sessions"
            if docs_and_dashboard_only
            else "analytics_integration_sessions"
        )
        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    select
                      install_id,
                      inferred_session_id,
                      mid,
                      started_at,
                      ended_at,
                      has_docs,
                      has_dashboard,
                      event_count,
                      tool_call_count,
                      stage_event_count,
                      last_completed_phase,
                      stage_events
                    from {view_name}
                    order by ended_at desc
                    limit %s
                    """,
                    (safe_limit,),
                )
                return [dict(row) for row in await cur.fetchall()]
    except Exception:
        logger.exception("Failed to fetch analytics integration sessions")
        return []
