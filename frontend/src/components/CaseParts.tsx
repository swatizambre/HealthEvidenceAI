/** Shared case pieces used by the case workspace and senior Reviews. */
import { useState } from "react";
import type { ChecklistGroup, ChecklistItem, DeskCitation, Stage } from "../deskApi";
import { useI18n, type MessageKey } from "../i18n";
import { documentTypeLabel } from "../labels";
import { Icon, ItemStatusPill, formatDate } from "../ui";

export const ILLUSTRATIVE_NOTE = "Illustrative field set — confirm with each insurer/TPA.";

const GROUP_ORDER: ChecklistGroup[] = ["form", "clinical", "documents"];

const GROUP_LABEL: Record<ChecklistGroup, string> = {
  form: "Form fields",
  clinical: "Clinical evidence",
  documents: "Documents",
};

export function Citations({ citations }: { citations: DeskCitation[] }) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <ul className="citations" aria-label="Chart citations">
      {citations.map((citation, index) => (
        <li key={`${citation.document_id}-${citation.chunk_id}-${index}`} className="citation">
          <blockquote>{citation.excerpt}</blockquote>
          <p className="citation-meta">
            <Icon name="doc" size={12} />
            <span>{documentTypeLabel(citation.source)}</span>
            {citation.date ? <span>{formatDate(citation.date)}</span> : null}
            <span className="citation-id">{citation.document_id}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const open = item.status !== "SUPPORTED";
  return (
    <li className={`check-item check-${item.status.toLowerCase()}`}>
      <div className="check-head">
        <ItemStatusPill status={item.status} />
        <p className="check-label">
          {item.label}
          {!item.required ? <span className="tag">Optional</span> : null}
        </p>
      </div>
      {item.reason ? <p className="check-reason">{item.reason}</p> : null}
      {open && item.fix_hint ? (
        <p className="check-fix">
          <Icon name="arrow-right" size={14} />
          <span>
            <strong>To fix:</strong> {item.fix_hint}
          </span>
        </p>
      ) : null}
      <Citations citations={item.citations} />
      {item.status === "SUPPORTED" && item.citations.length === 0 ? (
        <p className="check-reason muted">No excerpt attached to this item.</p>
      ) : null}
    </li>
  );
}

/** Checklist grouped as form / clinical / documents, citations shown inline. */
export function Checklist({ items }: { items: ChecklistItem[] }) {
  const [onlyOpen, setOnlyOpen] = useState(false);
  const visible = onlyOpen ? items.filter((item) => item.status !== "SUPPORTED") : items;

  return (
    <div className="checklist">
      <div className="checklist-bar">
        <p className="muted small">{ILLUSTRATIVE_NOTE}</p>
        <label className="switch">
          <input type="checkbox" checked={onlyOpen} onChange={(event) => setOnlyOpen(event.target.checked)} />
          <span>Show open items only</span>
        </label>
      </div>
      {visible.length === 0 ? (
        <p className="muted">Every required item is supported by the chart.</p>
      ) : null}
      {GROUP_ORDER.map((group) => {
        const groupItems = visible.filter((item) => item.group === group);
        if (groupItems.length === 0) {
          return null;
        }
        const supported = items.filter((item) => item.group === group && item.status === "SUPPORTED").length;
        const total = items.filter((item) => item.group === group).length;
        return (
          <section key={group} className="check-group" aria-label={GROUP_LABEL[group]}>
            <h3 className="check-group-title">
              {GROUP_LABEL[group]}
              <span className="muted">
                {supported} of {total} supported
              </span>
            </h3>
            <ul className="check-list">
              {groupItems.map((item) => (
                <ChecklistRow key={item.item_id} item={item} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

type StepId = "draft" | "ready" | "sent" | "query" | "approved" | "discharge" | "closed";

const STEPS: StepId[] = ["draft", "ready", "sent", "query", "approved", "discharge", "closed"];

const STAGE_STEP: Record<Stage, StepId> = {
  draft: "draft",
  ready_to_send: "ready",
  sent: "sent",
  query: "query",
  approved: "approved",
  enhancement: "approved",
  discharge_pending: "discharge",
  discharge_sent: "discharge",
  closed: "closed",
};

/** Draft → Ready → Sent → Query → Approved → Discharge → Closed. */
export function StageStepper({ stage, hadQuery }: { stage: Stage; hadQuery: boolean }) {
  const { t } = useI18n();
  const current = STEPS.indexOf(STAGE_STEP[stage]);
  return (
    <ol className="stepper" aria-label="Case stage">
      {STEPS.map((step, index) => {
        const skipped = step === "query" && index < current && !hadQuery;
        const state = index < current ? (skipped ? "skipped" : "done") : index === current ? "current" : "todo";
        return (
          <li key={step} className={`step step-${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="step-marker" aria-hidden="true">
              {state === "done" ? <Icon name="check" size={12} /> : index + 1}
            </span>
            <span className="step-label">{t(`step.${step}` as MessageKey)}</span>
            <span className="sr-only">
              {state === "done" ? " (done)" : state === "current" ? " (current)" : state === "skipped" ? " (not needed)" : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
