"""Healthcare Evidence MCP server (stdio).

Agents in-process use ``HealthcareMCPClient``. External hosts can run:

    python -m app.mcp.server
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined]

from app.core.config import get_settings
from app.db.session import create_db_engine, create_session_factory, init_db, prepare_sqlite_path
from app.mcp.tools import call_tool, list_tool_names

mcp = FastMCP("healthevidence-healthcare")


def _session_factory() -> Any:
    settings = get_settings()
    prepare_sqlite_path(settings.database_url)
    engine = create_db_engine(settings.database_url)
    init_db(engine)
    return create_session_factory(engine)


_FACTORY: Any = None


def _db() -> Any:
    global _FACTORY
    if _FACTORY is None:
        _FACTORY = _session_factory()
    return _FACTORY()


def _run(tool_name: str, agent: str, **kwargs: Any) -> str:
    session = _db()
    try:
        result = call_tool(session, tool_name=tool_name, agent=agent, arguments=kwargs)
        session.commit()
        return json.dumps(result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@mcp.tool()
def get_patient_record(patient_id: str, agent: str = "ClinicalEvidenceAgent") -> str:
    """Return a synthetic patient summary."""
    return _run("get_patient_record", agent, patient_id=patient_id)


@mcp.tool()
def get_patient_timeline(patient_id: str, agent: str = "ClinicalEvidenceAgent") -> str:
    """Return a synthetic patient timeline."""
    return _run("get_patient_timeline", agent, patient_id=patient_id)


@mcp.tool()
def get_policy(policy_id: str, agent: str = "PolicyAgent") -> str:
    """Return a payer policy document."""
    return _run("get_policy", agent, policy_id=policy_id)


@mcp.tool()
def get_policy_criteria(policy_id: str, agent: str = "PolicyAgent") -> str:
    """Return explicit policy criteria."""
    return _run("get_policy_criteria", agent, policy_id=policy_id)


@mcp.tool()
def search_clinical_evidence(
    query: str,
    patient_id: str | None = None,
    document_type: str | None = None,
    limit: int = 5,
    agent: str = "ClinicalEvidenceAgent",
) -> str:
    """Hybrid RAG search over synthetic clinical evidence."""
    return _run(
        "search_clinical_evidence",
        agent,
        query=query,
        patient_id=patient_id,
        document_type=document_type,
        limit=limit,
    )


@mcp.tool()
def get_evidence_chunk(chunk_id: str, agent: str = "EvidenceVerificationAgent") -> str:
    """Fetch one evidence chunk by id."""
    return _run("get_evidence_chunk", agent, chunk_id=chunk_id)


@mcp.tool()
def create_human_review(
    run_id: str,
    patient_id: str,
    reason: str,
    decision: str = "pending",
    agent: str = "AuthorizationAgent",
) -> str:
    """Create a human-review audit event."""
    return _run(
        "create_human_review",
        agent,
        run_id=run_id,
        patient_id=patient_id,
        reason=reason,
        decision=decision,
    )


@mcp.tool()
def list_tools() -> str:
    """List healthcare MCP tool names."""
    return json.dumps(list_tool_names())


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
