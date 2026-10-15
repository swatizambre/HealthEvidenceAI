import { useEffect, useState } from "react";
import {
  listConsents,
  recordConsent,
  type ConsentInput,
  type ConsentMethod,
  type ConsentPurpose,
  type ConsentRecord,
} from "../api";

const INGEST_PURPOSES: ConsentPurpose[] = ["prior_auth_evidence", "continuity_of_care"];

export interface ConsentDraft {
  /** Existing consent chosen from the patient's active consents ("" = record new). */
  consentId: string;
  purpose: ConsentPurpose;
  method: ConsentMethod;
  noticeVersion: string;
  grantedByName: string;
  language: string;
  evidenceRef: string;
}

export const emptyConsentDraft = (): ConsentDraft => ({
  consentId: "",
  purpose: "prior_auth_evidence",
  method: "written",
  noticeVersion: "",
  grantedByName: "",
  language: "en",
  evidenceRef: "",
});

export function consentDraftComplete(draft: ConsentDraft): boolean {
  if (draft.consentId) {
    return true;
  }
  return draft.noticeVersion.trim().length > 0 && draft.grantedByName.trim().length > 0;
}

function draftToInput(draft: ConsentDraft): ConsentInput {
  return {
    purpose: draft.purpose,
    method: draft.method,
    notice_version: draft.noticeVersion.trim(),
    granted_by_name: draft.grantedByName.trim(),
    language: draft.language.trim() || "en",
    evidence_ref: draft.evidenceRef.trim() || undefined,
  };
}

/**
 * Resolve the consent fields for an ingest request on a PHI desk.
 * Existing chart → stored consent_id (recording one first when needed).
 * New chart → inline consent stored by the server in the same transaction.
 */
export async function resolveIngestConsent(
  draft: ConsentDraft,
  patientId: string | undefined,
): Promise<{ consent_id?: string; consent?: ConsentInput }> {
  if (draft.consentId) {
    return { consent_id: draft.consentId };
  }
  const input = draftToInput(draft);
  if (patientId) {
    const stored = await recordConsent(patientId, input);
    return { consent_id: stored.consent_id };
  }
  return { consent: input };
}

export function ConsentCapture({
  patientId,
  draft,
  onChange,
  canRecord,
}: {
  patientId: string | undefined;
  draft: ConsentDraft;
  onChange: (next: ConsentDraft) => void;
  /** Patients cannot record consent themselves; they may only pick an active one. */
  canRecord: boolean;
}) {
  const [active, setActive] = useState<ConsentRecord[]>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setActive([]);
    setLoadError("");
    if (!patientId) {
      return;
    }
    listConsents(patientId)
      .then((body) => {
        if (!cancelled) {
          const usable = body.consents.filter(
            (item) => item.active && INGEST_PURPOSES.includes(item.purpose as ConsentPurpose),
          );
          setActive(usable);
          // Patients cannot record a new consent — preselect their newest active one.
          if (!canRecord && usable.length > 0) {
            onChange({ ...draft, consentId: usable[0].consent_id });
          }
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setLoadError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
    // Reload only when the target chart changes; draft edits must not refetch.
  }, [patientId, canRecord]);

  const set = (patch: Partial<ConsentDraft>) => onChange({ ...draft, ...patch });

  return (
    <fieldset className="span-2 consent-capture">
      <legend className="form-section-title">Patient consent (required on live records)</legend>
      {loadError ? (
        <p className="form-error" role="alert">
          {loadError}
        </p>
      ) : null}
      {patientId ? (
        <label className="field">
          <span>Consent on file</span>
          <select value={draft.consentId} onChange={(e) => set({ consentId: e.target.value })}>
            {canRecord ? <option value="">Record a new consent…</option> : null}
            {!canRecord && active.length === 0 ? (
              <option value="">No active consent — ask the desk to record one</option>
            ) : null}
            {active.map((item) => (
              <option key={item.consent_id} value={item.consent_id}>
                {item.consent_id} · {item.purpose.replace(/_/g, " ")} · notice {item.notice_version}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="muted small">New patient: the consent below is stored with this first visit.</p>
      )}
      {!draft.consentId && canRecord ? (
        <div className="form-grid">
          <label className="field">
            <span>Purpose</span>
            <select
              value={draft.purpose}
              onChange={(e) => set({ purpose: e.target.value as ConsentPurpose })}
            >
              <option value="prior_auth_evidence">Prior-authorization evidence</option>
              <option value="continuity_of_care">Continuity of care</option>
            </select>
          </label>
          <label className="field">
            <span>Method</span>
            <select
              value={draft.method}
              onChange={(e) => set({ method: e.target.value as ConsentMethod })}
            >
              <option value="written">Written (signed form)</option>
              <option value="electronic">Electronic</option>
              <option value="verbal_witnessed">Verbal, witnessed</option>
            </select>
          </label>
          <label className="field">
            <span>Notice version shown</span>
            <input
              value={draft.noticeVersion}
              onChange={(e) => set({ noticeVersion: e.target.value })}
              placeholder="notice-2026-10"
              maxLength={64}
              required
            />
          </label>
          <label className="field">
            <span>Granted by (patient or representative)</span>
            <input
              value={draft.grantedByName}
              onChange={(e) => set({ grantedByName: e.target.value })}
              maxLength={120}
              required
            />
          </label>
          <label className="field">
            <span>Language</span>
            <input
              value={draft.language}
              onChange={(e) => set({ language: e.target.value })}
              maxLength={16}
            />
          </label>
          <label className="field">
            <span>Signed form / reference (optional)</span>
            <input
              value={draft.evidenceRef}
              onChange={(e) => set({ evidenceRef: e.target.value })}
              maxLength={64}
            />
          </label>
        </div>
      ) : null}
    </fieldset>
  );
}
