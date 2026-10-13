"""In-process MCP client used by LangGraph agents."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.mcp.tools import TOOL_PERMISSIONS, call_tool, list_tool_names
from app.services.observability import span_timer


class HealthcareMCPClient:
    """Bridge agents → permissioned tools without unrestricted DB access."""

    def __init__(self, session: Session, *, agent: str, trace_id: str, run_id: str) -> None:
        self.session = session
        self.agent = agent
        self.trace_id = trace_id
        self.run_id = run_id

    def list_tools(self) -> list[str]:
        return list_tool_names()

    def call(self, tool_name: str, **arguments: Any) -> dict[str, Any]:
        with span_timer(
            trace_id=self.trace_id,
            run_id=self.run_id,
            agent=self.agent,
            node="mcp_call",
            tool=tool_name,
        ):
            try:
                return call_tool(
                    self.session,
                    tool_name=tool_name,
                    agent=self.agent,
                    arguments=arguments,
                )
            except AppError:
                raise
            except TypeError as exc:
                raise AppError("MCP_INVALID_ARGUMENTS", str(exc), 400) from exc
            except KeyError as exc:
                raise AppError("MCP_UNKNOWN_TOOL", str(exc), 404) from exc
            except Exception as exc:
                raise AppError("MCP_UNAVAILABLE", f"MCP tool failed: {exc}", 503) from exc

    def permissions(self) -> dict[str, str]:
        return dict(TOOL_PERMISSIONS)
