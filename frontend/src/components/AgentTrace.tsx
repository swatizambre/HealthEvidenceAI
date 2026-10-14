import type { CSSProperties } from "react";
import { agentDisplayName, nodeDisplayName, productStepDetail } from "../labels";

export type AgentTraceStep = {
  agent: string;
  node: string;
  detail?: string;
  status?: string;
};

type Props = {
  steps: AgentTraceStep[];
  scoringPath?: string;
  mcpTools?: string[];
  aiBrief?: string;
  compact?: boolean;
  /** When true, steps sit behind a disclosure (default for review desks). */
  collapsed?: boolean;
};

function statusLabel(status: string | undefined, detail?: string): string {
  const value = (status || "").toLowerCase();
  const detailLower = (detail || "").toLowerCase();
  if (detailLower === "paused" || value === "paused" || value === "waiting") {
    return "Waiting";
  }
  if (value === "ok" || value === "done" || value === "complete") {
    return "Done";
  }
  if (value === "error" || value === "failed") {
    return "Needs attention";
  }
  return status ? status.replace(/_/g, " ") : "";
}

export function AgentTrace({ steps, aiBrief, compact, collapsed = true }: Props) {
  if (!steps.length && !aiBrief) {
    return null;
  }

  const body = (
    <>
      {aiBrief ? <p className="agent-brief">{aiBrief}</p> : null}
      {steps.length > 0 ? (
        <ol className="agent-trace">
          {steps.map((step, index) => {
            const detail = productStepDetail(step.detail);
            return (
              <li key={`${step.agent}-${step.node}-${index}`} className="agent-trace-item">
                <span className="agent-trace-index" style={{ "--i": index } as CSSProperties}>
                  {index + 1}
                </span>
                <div className="agent-trace-body">
                  <strong>{agentDisplayName(step.agent)}</strong>
                  <span className="muted">
                    {nodeDisplayName(step.node)}
                    {step.status || step.detail
                      ? ` · ${statusLabel(step.status, step.detail)}`
                      : ""}
                  </span>
                  {detail ? <p className="agent-trace-detail">{detail}</p> : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </>
  );

  return (
    <section
      className={`agent-desk ${compact ? "compact" : ""}`}
      aria-label="Evidence preparation steps"
    >
      {collapsed ? (
        <details className="agent-desk-details">
          <summary className="agent-desk-summary">
            <span className="panel-title">Evidence prep · preparation</span>
            <span className="muted">
              {steps.length ? `${steps.length} steps · ` : ""}
              Decision support only — not an approval
            </span>
          </summary>
          {body}
        </details>
      ) : (
        <>
          <header className="agent-desk-head">
            <h3 className="panel-title">Evidence prep · preparation</h3>
            <p className="muted">Rule check and grounded prep before clinician confirmation</p>
          </header>
          {body}
        </>
      )}
    </section>
  );
}
