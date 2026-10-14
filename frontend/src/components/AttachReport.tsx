/** Attach a typed report (X-ray, implant quotation, MLC copy…) to a chart for the TPA checklist. */
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  REPORT_DOCUMENT_LABEL,
  attachPatientDocument,
  deskErrorMessage,
  isReportDocumentType,
  type ReportDocumentType,
} from "../deskApi";
import { Button, Notice } from "../ui";

const TYPES = Object.keys(REPORT_DOCUMENT_LABEL) as ReportDocumentType[];

export function AttachReport({
  patientId,
  caseId,
  initialType,
  gap,
  defaultOpen = false,
}: {
  patientId: string;
  caseId?: string;
  initialType?: string;
  gap?: string;
  defaultOpen?: boolean;
}) {
  const [documentType, setDocumentType] = useState<ReportDocumentType>(
    initialType && isReportDocumentType(initialType) ? initialType : "radiology_report",
  );
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedId, setSavedId] = useState("");

  useEffect(() => {
    if (initialType && isReportDocumentType(initialType)) setDocumentType(initialType);
  }, [initialType]);

  const validPatient = /^PAT-\d{6}$/.test(patientId);
  const disabled = !validPatient || content.trim().length < 10;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    setBusy(true);
    setError("");
    try {
      const saved = await attachPatientDocument({
        patient_id: patientId,
        document_type: documentType,
        content: content.trim(),
        case_id: caseId,
      });
      setSavedId(saved.document_id);
      setContent("");
    } catch (err) {
      setError(deskErrorMessage(err, "Could not attach the report."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="panel attach-report" id="attach-report" open={defaultOpen}>
      <summary>
        <span className="section-title">Attach a report or document</span>
        <span className="muted small">
          {gap ? `For checklist item: ${gap}` : "X-ray / CT report, implant quotation, MLC copy, ANC card…"}
        </span>
      </summary>
      <form className="stack-form" onSubmit={onSubmit}>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        {savedId ? (
          <Notice tone="success" title={`Saved to the chart as ${savedId}`}>
            {caseId ? (
              <>
                The checklist updates on the case. <Link to={`/cases/${encodeURIComponent(caseId)}`}>Back to {caseId}</Link>
              </>
            ) : (
              "The checklist updates on the next refresh."
            )}
          </Notice>
        ) : null}
        {!validPatient ? (
          <p className="muted small">Pick an existing patient (PAT-ID) above before attaching a report.</p>
        ) : null}
        <label className="field">
          <span>Document type</span>
          <select value={documentType} onChange={(e) => setDocumentType(e.target.value as ReportDocumentType)}>
            {TYPES.map((key) => (
              <option key={key} value={key}>
                {REPORT_DOCUMENT_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Report text</span>
          <textarea
            rows={5}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste or type the report as issued, e.g. “X-ray knee report (weight-bearing): …”"
          />
          <span className="field-hint">Only the checklist's accepted document types count as the document itself.</span>
        </label>
        <div className="button-row">
          <Button type="submit" variant="primary" icon="doc" loading={busy} disabled={disabled}>
            Save report to chart
          </Button>
        </div>
      </form>
    </details>
  );
}
