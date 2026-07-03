from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

import click
import dotenv
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from .config import is_local_development
from .storage import fetch_integration_sessions, shutdown


PHASES = ["setup", "prd", "architecture", "backend", "frontend", "validation", "live"]


def _json_default(value: Any) -> str:
    return str(value)


def _json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        json.dumps(payload, default=_json_default),
        status_code=status_code,
        media_type="application/json",
    )


def _serialize_session(row: dict[str, Any]) -> dict[str, Any]:
    started_at = row.get("started_at")
    ended_at = row.get("ended_at")
    duration_seconds = None
    if isinstance(started_at, datetime) and isinstance(ended_at, datetime):
        duration_seconds = int((ended_at - started_at).total_seconds())

    return {
        "install_id": row.get("install_id"),
        "inferred_session_id": str(row.get("inferred_session_id")),
        "mid": row.get("mid"),
        "started_at": _json_default(started_at) if started_at else None,
        "ended_at": _json_default(ended_at) if ended_at else None,
        "duration_seconds": duration_seconds,
        "has_docs": bool(row.get("has_docs")),
        "has_dashboard": bool(row.get("has_dashboard")),
        "event_count": row.get("event_count", 0),
        "tool_call_count": row.get("tool_call_count", 0),
        "stage_event_count": row.get("stage_event_count", 0),
        "last_completed_phase": row.get("last_completed_phase"),
        "stage_events": row.get("stage_events") or [],
    }


def _summarize(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    phase_counts = Counter()
    for session in sessions:
        phase = session.get("last_completed_phase")
        if phase:
            phase_counts[phase] += 1

    return {
        "sessions": len(sessions),
        "docs_and_dashboard_sessions": sum(
            1 for session in sessions if session["has_docs"] and session["has_dashboard"]
        ),
        "docs_only_sessions": sum(
            1 for session in sessions if session["has_docs"] and not session["has_dashboard"]
        ),
        "dashboard_only_sessions": sum(
            1 for session in sessions if session["has_dashboard"] and not session["has_docs"]
        ),
        "funnel": [
            {"phase": phase, "completed_sessions": phase_counts.get(phase, 0)}
            for phase in PHASES
        ],
    }


async def health(_request: Request) -> Response:
    return _json_response({"status": "ok"})


async def api_sessions(request: Request) -> Response:
    docs_and_dashboard_only = request.query_params.get("all") not in ("1", "true", "yes")
    limit = int(request.query_params.get("limit", "100"))
    rows = await fetch_integration_sessions(
        docs_and_dashboard_only=docs_and_dashboard_only,
        limit=limit,
    )
    return _json_response([_serialize_session(row) for row in rows])


async def api_summary(_request: Request) -> Response:
    rows = await fetch_integration_sessions(docs_and_dashboard_only=False, limit=1000)
    sessions = [_serialize_session(row) for row in rows]
    return _json_response(_summarize(sessions))




def build_app() -> Starlette:
    routes = []
    if is_local_development():
        routes = [
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/api/sessions", endpoint=api_sessions, methods=["GET"]),
            Route("/api/summary", endpoint=api_summary, methods=["GET"]),
        ]

    async def lifespan(_app: Starlette):
        try:
            yield
        finally:
            await shutdown()

    return Starlette(debug=False, routes=routes, lifespan=lifespan)


@click.command()
@click.option(
    "--host",
    default="0.0.0.0",
    envvar="ANALYTICS_HOST",
    show_default=True,
    help="Host to bind inside the analytics pod.",
)
@click.option(
    "--port",
    default=9090,
    envvar="ANALYTICS_PORT",
    show_default=True,
    type=int,
    help="Port to listen on inside the analytics pod.",
)
def main(host: str, port: int) -> None:
    """Run the internal MCP analytics app."""
    dotenv.load_dotenv()
    uvicorn.run(build_app(), host=host, port=port)
