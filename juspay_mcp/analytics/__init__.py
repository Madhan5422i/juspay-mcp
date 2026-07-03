"""Server-side analytics for the combined Docs + Dashboard MCP deployment."""

from .context import (
    AnalyticsRequestContext,
    clear_current_context,
    get_current_context,
    set_current_context,
)
from .tracker import record_stage_status, record_tool_call
from .storage import fetch_integration_sessions

__all__ = [
    "AnalyticsRequestContext",
    "clear_current_context",
    "get_current_context",
    "fetch_integration_sessions",
    "record_stage_status",
    "record_tool_call",
    "set_current_context",
]
