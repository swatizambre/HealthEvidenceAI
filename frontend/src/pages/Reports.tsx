import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  fetchDocumentFileBlob,
  listPatientReports,
  uploadPatientReport,
  type ReportItem,
} from "../api";
import { useRole } from "../roleContext";
import { Button, EmptyState, Notice, Skeleton, formatDateTime } from "../ui";

const ALL_KIND_OPTIONS = [
  { id: "auto", label: "Auto-detect" },
  { id: "lab_report", label: "Lab report (CBC, HbA1c…)" },
  { id: "imaging_report", label: "Imaging report (CT, MRI, X-ray…)" },
  { id: "prescription", label: "Prescription" },
  { id: "clinical_note", label: "Clinical note" },
] as const;

const SCAN_KIND_OPTIONS = [
  { id: "imaging_report", label: "CT / MRI / X-ray report" },
  { id: "auto", label: "Auto-detect" },
] as const;

type UploadKind = (typeof ALL_KIND_OPTIONS)[number]["id"];
export type LibraryScope = "all" | "scans";

function typeLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function bytesLabel(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function isScanReport(row: ReportItem): boolean {
  if (row.document_type === "radiology_report") return true;
  const hay = `${row.title} ${row.source} ${row.original_filename} ${row.document_type}`;
  return /\b(ct|mri|x-?ray|usg|ultrasound|scan|radiolog|imaging|pet|mammogra)\b/i.test(hay);
}

export function ScansPage() {
  return <DocumentLibraryPage scope="scans" />;
}

export function ReportsPage() {
  return <DocumentLibraryPage scope="all" />;
}

function DocumentLibraryPage({ scope }: { scope: LibraryScope }) {
  const { patientId: routePatientId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isPatient, myPatientId } = useRole();
  const patientId = (routePatientId || myPatientId || "").toUpperCase();
  const focusDoc = searchParams.get("doc") || "";
  const isScans = scope === "scans";
  const kindOptions = isScans ? SCAN_KIND_OPTIONS : ALL_KIND_OPTIONS;

  const [reports, setReports] = useState<ReportItem[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [kind, setKind] = useState<UploadKind>(isScans ? "imaging_report" : "auto");
  const [selectedId, setSelectedId] = useState(focusDoc);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewText, setPreviewText] = useState("");

  const load = useCallback(async () => {
    if (!/^PAT-\d{6}$/.test(patientId)) {
      setReports([]);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = await listPatientReports(patientId);
      setReports(body.reports);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load library.");
      setReports([]);
    } finally {
      setBusy(false);
    }
  }, [patientId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (focusDoc) setSelectedId(focusDoc);
  }, [focusDoc]);

  useEffect(() => {
    setKind(isScans ? "imaging_report" : "auto");
  }, [isScans]);

  const visible = useMemo(() => {
    if (!reports) return null;
    return isScans ? reports.filter(isScanReport) : reports;
  }, [reports, isScans]);

  const selected = useMemo(
    () => visible?.find((row) => row.document_id === selectedId) || null,
    [visible, selectedId],
  );

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    async function openPreview(report: ReportItem) {
      setPreviewBusy(true);
      setPreviewUrl(null);
      setPreviewText("");
      setPreviewType("");
      try {
        if (!report.has_file) {
          setPreviewText(report.content_excerpt || "No original file attached — text extract only.");
          return;
        }
        const { blob, contentType } = await fetchDocumentFileBlob(report.document_id);
        if (cancelled) return;
        setPreviewType(contentType);
        if (contentType.startsWith("text/") || report.preview_kind === "text") {
          setPreviewText(await blob.text());
          return;
        }
        const url = URL.createObjectURL(blob);
        revoked = url;
        setPreviewUrl(url);
      } catch (err) {
        if (!cancelled) {
          setPreviewText(err instanceof Error ? err.message : "Could not open the file.");
        }
      } finally {
        if (!cancelled) setPreviewBusy(false);
      }
    }
    if (selected) {
      void openPreview(selected);
    } else {
      setPreviewUrl(null);
      setPreviewText("");
    }
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [selected]);

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("report") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file || !/^PAT-\d{6}$/.test(patientId)) return;
    setUploadBusy(true);
    setError("");
    try {
      const uploadKind = isScans && kind === "auto" ? "imaging_report" : kind;
      const saved = await uploadPatientReport(patientId, file, uploadKind);
      await load();
      setSelectedId(saved.document_id);
      setSearchParams({ doc: saved.document_id });
      form.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploadBusy(false);
    }
  }

  function selectReport(id: string) {
    setSelectedId(id);
    setSearchParams(id ? { doc: id } : {});
  }

  const title = isScans ? "Scans" : "Reports";
  const sibling = isScans
    ? { to: `/patients/${patientId}/reports`, label: "All reports" }
    : { to: `/patients/${patientId}/scans`, label: "Scans only" };

  if (!/^PAT-\d{6}$/.test(patientId)) {
    return (
      <section className="page">
        <Notice tone="warning" title="Choose a patient">
          Open a chart first, then use {title}.{" "}
          <Link to={isPatient ? "/my-record" : "/patients"}>Go to patients</Link>
        </Notice>
      </section>
    );
  }

  return (
    <section className="page reports-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={isPatient ? "/my-record" : "/patients"}>
          {isPatient ? "My record" : "Patients"}
        </Link>
        <span aria-hidden="true">/</span>
        <Link to={`/patients/${patientId}`}>{patientId}</Link>
        <span aria-hidden="true">/</span>
        <span>{title}</span>
      </nav>

      <header className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-sub">
            {isScans
              ? "CT, MRI, X-ray, and ultrasound reports — upload the PDF or a photo of the film and preview it here. Full DICOM PACS viewing is not in this build."
              : "Lab PDFs, prescriptions, and clinical notes — upload, extract, and preview the original file."}
          </p>
        </div>
        <div className="page-actions">
          <Link className="button ghost" to={sibling.to}>
            {sibling.label}
          </Link>
          <Button variant="ghost" onClick={() => void load()} loading={busy}>
            Refresh
          </Button>
          <Link className="button ghost" to={`/patients/${patientId}`}>
            Back to chart
          </Link>
        </div>
      </header>

      {error ? (
        <Notice tone="danger" title={title}>
          {error}
        </Notice>
      ) : null}

      <form className="report-upload panel" onSubmit={(e) => void onUpload(e)}>
        <h2 className="form-section-title">{isScans ? "Upload a scan report" : "Upload a report"}</h2>
        <div className="report-upload-row">
          <label className="field">
            <span>Type</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as UploadKind)}>
              {kindOptions.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field grow">
            <span>File (PDF or image · max 15 MB)</span>
            <input
              name="report"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,application/pdf,image/*"
              required
            />
          </label>
          <Button type="submit" variant="primary" icon="doc" loading={uploadBusy}>
            Upload &amp; extract
          </Button>
        </div>
      </form>

      <div className="reports-layout">
        <div className="reports-list panel">
          <h2 className="form-section-title">Library</h2>
          {busy && !visible ? <Skeleton lines={4} label={`Loading ${title.toLowerCase()}`} /> : null}
          {visible && visible.length === 0 ? (
            <EmptyState
              icon="doc"
              title={isScans ? "No scans yet" : "No reports yet"}
            />
          ) : null}
          {visible && visible.length > 0 ? (
            <ul className="report-items">
              {visible.map((row) => (
                <li key={row.document_id}>
                  <button
                    type="button"
                    className={`report-item${selectedId === row.document_id ? " is-selected" : ""}`}
                    onClick={() => selectReport(row.document_id)}
                  >
                    <span className="report-item-title">
                      {row.title || row.original_filename || row.document_id}
                    </span>
                    <span className="muted small">
                      {typeLabel(row.document_type)}
                      {row.created_at ? ` · ${formatDateTime(row.created_at)}` : ""}
                      {row.has_file ? ` · ${bytesLabel(row.byte_size)}` : " · text only"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="report-preview panel" aria-live="polite">
          <h2 className="form-section-title">Preview</h2>
          {!selected ? (
            <p className="muted">
              {isScans
                ? "Select a scan report to preview the PDF or photo."
                : "Select a report to preview the original PDF or image."}
            </p>
          ) : (
            <>
              <p className="report-preview-meta">
                <strong>{selected.title || selected.original_filename || selected.document_id}</strong>
                <span className="muted small">
                  {" "}
                  · {typeLabel(selected.document_type)}
                  {selected.has_file ? ` · ${selected.content_type || selected.preview_kind}` : ""}
                </span>
              </p>
              {previewBusy ? <Skeleton lines={3} label="Opening file" /> : null}
              {!previewBusy &&
              previewUrl &&
              (previewType.includes("pdf") || selected.preview_kind === "pdf") ? (
                <iframe className="report-frame" title="PDF preview" src={previewUrl} />
              ) : null}
              {!previewBusy &&
              previewUrl &&
              (previewType.startsWith("image/") || selected.preview_kind === "image") ? (
                <img
                  className="report-image"
                  src={previewUrl}
                  alt={selected.original_filename || "Scan"}
                />
              ) : null}
              {!previewBusy && previewText ? (
                <pre className="source-text report-text">{previewText}</pre>
              ) : null}
              {!previewBusy && selected.content_excerpt && !previewUrl && !previewText ? (
                <pre className="source-text report-text">{selected.content_excerpt}</pre>
              ) : null}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
