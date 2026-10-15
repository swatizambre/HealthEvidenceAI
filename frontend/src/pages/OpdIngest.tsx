import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  attachDocumentFile,
  getConsentCapabilities,
  getHospitalPipelineStatus,
  getPatient,
  getPatients,
  getPolicies,
  extractOpdDocument,
  getSpecialties,
  ingestOpdFhir,
  ingestOpdPacket,
  simulateHospitalVisit,
  type DocumentExtractResult,
  type HospitalPipelineRun,
  type HospitalPipelineStatus,
  type OpdIngestResult,
  type PatientSummary,
  type PolicySummary,
} from "../api";
import {
  ConsentCapture,
  consentDraftComplete,
  emptyConsentDraft,
  resolveIngestConsent,
  type ConsentDraft,
} from "../components/ConsentCapture";
import { AttachReport } from "../components/AttachReport";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { policyOptionLabel } from "../labels";
import { printVisitSummary } from "../printSheet";
import { pushRecentPatient } from "../recentPatients";
import { useRole } from "../roleContext";

type Mode = "visit" | "fhir";

type DxRow = { display: string; code: string };
type LabRow = { test_name: string; value: string; unit: string };
type MedRow = {
  name: string;
  dose: string;
  frequency: string;
  status: "active" | "discontinued";
};

const emptyDx = (): DxRow => ({ display: "", code: "" });
const emptyLab = (): LabRow => ({ test_name: "", value: "", unit: "mg/dL" });
const emptyMed = (): MedRow => ({
  name: "",
  dose: "",
  frequency: "",
  status: "active",
});

const SAMPLE_FHIR = `{
  "resourceType": "Bundle",
  "type": "collection",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "p1",
        "identifier": [{ "system": "urn:hospital:mrn", "value": "UHID-77881" }],
        "name": [{ "family": "Patel", "given": ["Asha"] }],
        "gender": "female",
        "birthDate": "1988-04-12"
      }
    },
    {
      "resource": {
        "resourceType": "Encounter",
        "id": "e1",
        "identifier": [{ "value": "OPD-2026-4412" }],
        "class": { "code": "AMB" },
        "reasonCode": [{ "text": "Medication review due (situation)" }]
      }
    },
    {
      "resource": {
        "resourceType": "Condition",
        "code": { "text": "Gingivitis (disorder)" }
      }
    }
  ]
}`;

export function OpdIngestPage() {
  const [searchParams] = useSearchParams();
  const { facilityLabel, isPatient, myPatientId, label: roleLabel } = useRole();
  const linkedPatient = searchParams.get("patient") || (isPatient ? myPatientId : "");
  const focus = searchParams.get("focus") || "";
  const gapHint = searchParams.get("gap") || "";
  const specialtyHint = searchParams.get("specialty") || "";
  const draftHint = searchParams.get("draft") || "";
  const policyParam = searchParams.get("policy") || "";
  const caseParam = searchParams.get("case") || "";
  const [mode, setMode] = useState<Mode>("visit");
  const [feedOpenInitially] = useState(() => window.location.hash === "#hospital-feed");
  const [facilityName, setFacilityName] = useState(facilityLabel);
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerHits, setPickerHits] = useState<PatientSummary[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState(linkedPatient);
  const [mrn, setMrn] = useState(linkedPatient || "");
  const [visitNumber, setVisitNumber] = useState(() => `OPD-${Date.now()}`);
  const [displayName, setDisplayName] = useState("");
  const [sex, setSex] = useState("unknown");
  const [birthDate, setBirthDate] = useState("");
  const [department, setDepartment] = useState(specialtyHint || "General medicine");
  const [specialties, setSpecialties] = useState<string[]>([]);
  const [attending, setAttending] = useState("");
  const [chiefComplaint, setChiefComplaint] = useState(() =>
    gapHint && (focus === "note" || !focus)
      ? `Documentation for review gap: ${gapHint}`
      : "",
  );
  const [hpi, setHpi] = useState(() =>
    focus === "note" || !focus ? draftHint.slice(0, 4000) : "",
  );
  const [assessmentPlan, setAssessmentPlan] = useState(() =>
    focus === "note" || !focus ? "" : draftHint.slice(0, 2000),
  );
  const [diagnoses, setDiagnoses] = useState<DxRow[]>(() =>
    focus === "diagnoses" && gapHint
      ? [{ display: gapHint.slice(0, 120), code: "" }]
      : [emptyDx()],
  );
  const [knownConditions, setKnownConditions] = useState<string[]>([]);
  const [labRows, setLabRows] = useState<LabRow[]>(() =>
    focus === "labs" && gapHint
      ? [{ test_name: gapHint.slice(0, 80), value: "", unit: "mg/dL" }]
      : [emptyLab()],
  );
  const [medRows, setMedRows] = useState<MedRow[]>(() =>
    focus === "meds" && gapHint
      ? [{ name: gapHint.slice(0, 80), dose: "", frequency: "", status: "active" }]
      : [emptyMed()],
  );
  const [extractBusy, setExtractBusy] = useState(false);
  const [extractKind, setExtractKind] = useState<
    "auto" | "lab_report" | "prescription" | "clinical_note"
  >("auto");
  const [extractMeta, setExtractMeta] = useState<DocumentExtractResult | null>(null);
  const [pendingReportFile, setPendingReportFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [bp, setBp] = useState("");
  const [hr, setHr] = useState("");
  const [temp, setTemp] = useState("");
  const [showMore, setShowMore] = useState(
    () =>
      Boolean(draftHint) ||
      focus === "labs" ||
      focus === "meds" ||
      focus === "diagnoses",
  );
  const [procedure, setProcedure] = useState("");
  const [policyId, setPolicyId] = useState(policyParam || "");
  const [includeInsurance, setIncludeInsurance] = useState(
    () => Boolean(policyParam) || Boolean(caseParam),
  );
  const [advancedOpen, setAdvancedOpen] = useState(
    () => window.location.hash === "#hospital-feed" || window.location.hash === "#fhir",
  );
  const [fhirJson, setFhirJson] = useState(SAMPLE_FHIR);
  const [consentAttested, setConsentAttested] = useState(false);
  // PHI desks need a stored consent (selector / inline form) instead of the checkbox.
  const [consentRequired, setConsentRequired] = useState(false);
  const [consentDraft, setConsentDraft] = useState<ConsentDraft>(emptyConsentDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<OpdIngestResult | null>(null);
  const [pipeStatus, setPipeStatus] = useState<HospitalPipelineStatus | null>(null);
  const [pipeRun, setPipeRun] = useState<HospitalPipelineRun | null>(null);
  const [pipeBusy, setPipeBusy] = useState(false);
  const [pipeTick, setPipeTick] = useState(0);
  const complaintRef = useRef<HTMLInputElement | null>(null);

  const loadPipeline = useCallback(async () => {
    if (isPatient) {
      return;
    }
    try {
      const status = await getHospitalPipelineStatus();
      setPipeStatus(status);
    } catch {
      /* pipeline optional until staff token / API up */
    }
  }, [isPatient]);

  const { lastUpdatedAt: pipeUpdatedAt, refreshNow: refreshPipeline, pushConnected } =
    useLiveRefresh(loadPipeline, {
      intervalMs: 45_000,
      enabled: !isPatient,
    });

  useEffect(() => {
    let cancelled = false;
    void getConsentCapabilities().then((caps) => {
      if (!cancelled) {
        setConsentRequired(caps.consent_mode === "stored_required");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setPipeTick((n) => n + 1), 5_000);
    return () => window.clearInterval(id);
  }, []);
  void pipeTick;

  useEffect(() => {
    if (window.location.hash === "#hospital-feed") {
      document.getElementById("hospital-feed")?.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  async function onSimulateHospitalFeed() {
    setPipeBusy(true);
    setError("");
    setPipeRun(null);
    const targetPatient =
      selectedPatientId && /^PAT-\d{6}$/.test(selectedPatientId)
        ? selectedPatientId
        : "PAT-000001";
    try {
      const run = await simulateHospitalVisit({
        patient_id: targetPatient,
        policy_id: policyId || "POL-000001",
      });
      setPipeRun(run);
      if (run.patient_id) {
        pushRecentPatient({
          patient_id: run.patient_id,
          display_name: displayName.trim() || run.patient_id,
        });
        setSelectedPatientId(run.patient_id);
        setMrn(run.patient_id);
      }
      setResult({
        ingest_id: run.ingest_id || run.run_id,
        patient_id: run.patient_id || targetPatient,
        encounter_id: run.encounter_id || "",
        external_patient_id: "",
        document_ids: run.document_ids || [],
        case_id: run.case_id || null,
        created: Boolean(run.created),
        source: run.source,
        disclaimer: run.disclaimer || "",
      });
      refreshPipeline();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hospital feed simulation failed");
    } finally {
      setPipeBusy(false);
    }
  }

  useEffect(() => {
    getPolicies()
      .then((body) => {
        setPolicies(body.policies);
        if (policyParam) {
          const preferred = body.policies.find((item) => item.policy_id === policyParam);
          if (preferred) setPolicyId(preferred.policy_id);
        }
      })
      .catch((err: Error) => setError(err.message));
    getSpecialties()
      .then((body) => setSpecialties(body.specialties))
      .catch(() => setSpecialties([]));
  }, [policyParam]);

  useEffect(() => {
    // Keep gap/specialty coaching in sync when deep-linked from packet or Reviews.
    if (specialtyHint) {
      setDepartment(specialtyHint);
    }
    if (focus === "labs" && gapHint) {
      setLabRows([{ test_name: gapHint.slice(0, 80), value: "", unit: "mg/dL" }]);
      setShowMore(true);
    }
    if (focus === "meds" && gapHint) {
      setMedRows([{ name: gapHint.slice(0, 80), dose: "", frequency: "", status: "active" }]);
      setShowMore(true);
    }
    if (focus === "diagnoses" && gapHint) {
      setDiagnoses([{ display: gapHint.slice(0, 120), code: "" }]);
      setShowMore(true);
    }
    if ((focus === "note" || !focus) && gapHint) {
      setChiefComplaint(`Documentation for review gap: ${gapHint}`);
    }
  }, [focus, gapHint, specialtyHint]);

  useEffect(() => {
    if (!linkedPatient || !/^PAT-\d{6}$/.test(linkedPatient)) {
      window.setTimeout(() => complaintRef.current?.focus(), 50);
      return;
    }
    getPatient(linkedPatient)
      .then((patient) => {
        setSelectedPatientId(patient.patient_id);
        setMrn(patient.patient_id);
        setDisplayName(patient.demographics.synthetic_name);
        setSex(patient.demographics.sex || "unknown");
        setBirthDate(patient.demographics.date_of_birth || "");
        setKnownConditions(patient.conditions || []);
        if ((patient.conditions || []).length > 0) {
          const fromChart = patient.conditions
            .slice(0, 12)
            .map((display) => ({ display, code: "" }));
          if (focus === "diagnoses" && gapHint) {
            const already = fromChart.some(
              (row) => row.display.toLowerCase() === gapHint.toLowerCase(),
            );
            setDiagnoses(
              already
                ? fromChart
                : [{ display: gapHint.slice(0, 120), code: "" }, ...fromChart],
            );
          } else {
            setDiagnoses(fromChart);
          }
        } else if (focus === "diagnoses" && gapHint) {
          setDiagnoses([{ display: gapHint.slice(0, 120), code: "" }]);
        }
        pushRecentPatient({
          patient_id: patient.patient_id,
          display_name: patient.demographics.synthetic_name,
        });
        window.setTimeout(() => complaintRef.current?.focus(), 50);
      })
      .catch(() => {
        /* keep manual entry */
      });
  }, [linkedPatient]);

  useEffect(() => {
    if (isPatient) {
      setSelectedPatientId(myPatientId);
      setMrn(myPatientId);
      setPickerHits([]);
      setPickerQuery("");
    }
  }, [isPatient, myPatientId]);

  useEffect(() => {
    const q = pickerQuery.trim();
    if (isPatient || q.length < 2) {
      setPickerHits([]);
      return;
    }
    const timer = window.setTimeout(() => {
      getPatients({ limit: 8, q })
        .then((body) => setPickerHits(body.patients))
        .catch(() => setPickerHits([]));
    }, 160);
    return () => window.clearTimeout(timer);
  }, [pickerQuery, isPatient]);

  function selectExisting(patient: PatientSummary) {
    setSelectedPatientId(patient.patient_id);
    setMrn(patient.patient_id);
    setDisplayName(patient.synthetic_name);
    setSex(patient.sex || "unknown");
    setKnownConditions(patient.conditions || []);
    if ((patient.conditions || []).length > 0) {
      setDiagnoses(patient.conditions.slice(0, 12).map((display) => ({ display, code: "" })));
    } else {
      setDiagnoses([emptyDx()]);
    }
    setPickerQuery("");
    setPickerHits([]);
    pushRecentPatient({
      patient_id: patient.patient_id,
      display_name: patient.synthetic_name,
    });
    complaintRef.current?.focus();
  }

  function updateDx(index: number, patch: Partial<DxRow>) {
    setDiagnoses((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addDxRow() {
    setDiagnoses((rows) => [...rows, emptyDx()]);
  }

  function removeDxRow(index: number) {
    setDiagnoses((rows) => (rows.length <= 1 ? [emptyDx()] : rows.filter((_, i) => i !== index)));
  }

  function toggleKnownCondition(condition: string) {
    setDiagnoses((rows) => {
      const exists = rows.some(
        (row) => row.display.trim().toLowerCase() === condition.toLowerCase(),
      );
      if (exists) {
        const next = rows.filter(
          (row) => row.display.trim().toLowerCase() !== condition.toLowerCase(),
        );
        return next.length > 0 ? next : [emptyDx()];
      }
      const blankIndex = rows.findIndex((row) => !row.display.trim());
      if (blankIndex >= 0) {
        return rows.map((row, i) => (i === blankIndex ? { display: condition, code: "" } : row));
      }
      return [...rows, { display: condition, code: "" }];
    });
  }

  // A consent picked for one chart must never carry over to another patient.
  useEffect(() => {
    setConsentDraft((draft) => (draft.consentId ? { ...draft, consentId: "" } : draft));
  }, [selectedPatientId]);

  const consentReady = consentRequired ? consentDraftComplete(consentDraft) : consentAttested;

  async function onExtractFile(file: File | null) {
    if (!file) {
      return;
    }
    setExtractBusy(true);
    setError("");
    setExtractMeta(null);
    setPendingReportFile(file);
    try {
      const extracted = await extractOpdDocument(file, extractKind);
      setExtractMeta(extracted);
      setShowMore(true);
      if (extracted.chief_complaint?.trim()) {
        setChiefComplaint(extracted.chief_complaint.trim());
      }
      if (extracted.history_of_present_illness?.trim()) {
        setHpi(extracted.history_of_present_illness.trim());
      }
      if (extracted.assessment_and_plan?.trim()) {
        setAssessmentPlan(extracted.assessment_and_plan.trim());
      } else if (extracted.note?.trim() && !assessmentPlan.trim()) {
        setAssessmentPlan(extracted.note.trim().slice(0, 2000));
      }
      if (extracted.procedure?.trim()) {
        setProcedure(extracted.procedure.trim());
      }
      if (extracted.diagnoses?.length) {
        setDiagnoses(
          extracted.diagnoses.map((row) => ({
            display: row.display,
            code: row.code || "",
          })),
        );
      }
      const labs = extracted.labs || [];
      if (labs.length) {
        setLabRows(
          labs.map((row) => ({
            test_name: row.test_name,
            value: row.value,
            unit: row.unit || "",
          })),
        );
      }
      const meds = extracted.medications || [];
      if (meds.length) {
        setMedRows(
          meds.map((row) => ({
            name: row.name,
            dose: row.dose || "",
            frequency: row.frequency || "",
            status: row.status === "discontinued" ? "discontinued" : "active",
          })),
        );
      }
      for (const vital of extracted.vitals || []) {
        const name = vital.name.toLowerCase();
        if (name.includes("blood") || name === "bp") {
          setBp(vital.value);
        } else if (name.includes("heart") || name === "hr" || name.includes("pulse")) {
          setHr(vital.value);
        } else if (name.includes("temp")) {
          setTemp(vital.value);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document extract failed");
    } finally {
      setExtractBusy(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  async function onSubmitVisit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const vitals = [];
      if (bp.trim()) vitals.push({ name: "Blood pressure", value: bp.trim(), unit: "mmHg" });
      if (hr.trim()) vitals.push({ name: "Heart rate", value: hr.trim(), unit: "/min" });
      if (temp.trim()) vitals.push({ name: "Temperature", value: temp.trim(), unit: "C" });

      const dxPayload = diagnoses
        .map((row) => ({
          display: row.display.trim(),
          code: row.code.trim() || undefined,
          code_system: "ICD-10" as const,
        }))
        .filter((row) => row.display);

      const boundPatient =
        isPatient
          ? myPatientId
          : selectedPatientId && /^PAT-\d{6}$/.test(selectedPatientId)
            ? selectedPatientId
            : undefined;

      const consentFields = consentRequired
        ? await resolveIngestConsent(consentDraft, boundPatient)
        : {};

      const body = await ingestOpdPacket({
        mrn: isPatient ? myPatientId : mrn.trim(),
        visit_number: visitNumber.trim(),
        patient_id: boundPatient,
        display_name: displayName.trim() || undefined,
        sex,
        birth_date: birthDate || undefined,
        facility_name: facilityName.trim() || facilityLabel,
        department: department.trim() || "OPD",
        visit_type: "outpatient",
        attending_provider: attending.trim() || undefined,
        chief_complaint: chiefComplaint.trim() || undefined,
        history_of_present_illness: hpi.trim() || undefined,
        assessment_and_plan: assessmentPlan.trim() || undefined,
        diagnoses: dxPayload,
        vitals,
        labs: labRows
          .map((row) => ({
            test_name: row.test_name.trim(),
            value: row.value.trim() || "nr",
            unit: row.unit.trim(),
          }))
          .filter((row) => row.test_name),
        medications: medRows
          .map((row) => ({
            name: row.name.trim(),
            dose: row.dose.trim() || undefined,
            frequency: row.frequency.trim() || undefined,
            status: row.status,
          }))
          .filter((row) => row.name),
        note: extractMeta?.note?.trim() || undefined,
        procedure: (includeInsurance ? procedure.trim() : "") || "Outpatient visit",
        policy_id: includeInsurance && policyId ? policyId : undefined,
        source: "his_export",
        synthetic: !consentRequired,
        consent_attested: consentRequired ? true : consentAttested,
        ...consentFields,
      });
      // Keep the original PDF/image on the first chart document created by this visit.
      if (pendingReportFile && body.document_ids?.length) {
        try {
          await attachDocumentFile(body.document_ids[0], pendingReportFile);
          setPendingReportFile(null);
        } catch (attachErr) {
          setError(
            attachErr instanceof Error
              ? `Visit saved, but attaching the original file failed: ${attachErr.message}`
              : "Visit saved, but attaching the original file failed.",
          );
        }
      }
      setResult(body);
      pushRecentPatient({
        patient_id: body.patient_id,
        display_name: displayName || body.patient_id,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "OPD ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitFhir(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const bundle = JSON.parse(fhirJson) as Record<string, unknown>;
      const fhirPatient =
        selectedPatientId && /^PAT-\d{6}$/.test(selectedPatientId) ? selectedPatientId : undefined;
      const consentFields = consentRequired
        ? await resolveIngestConsent(consentDraft, fhirPatient)
        : {};
      const body = await ingestOpdFhir({
        bundle,
        procedure: procedure.trim() || "Outpatient visit",
        policy_id: includeInsurance && policyId ? policyId : undefined,
        patient_id: consentRequired ? fhirPatient : undefined,
        synthetic: !consentRequired,
        consent_attested: consentRequired ? true : consentAttested,
        ...consentFields,
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "FHIR ingest failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1 className="page-title">Visit note</h1>
          <p className="page-sub">
            {isPatient
              ? "Record today’s visit so every future clinician can see it in your lifelong chart."
              : "Document today’s visit — facility, specialty, complaint, plan — then save to the chart."}
          </p>
        </div>
      </header>

      {gapHint ? (
        <div className="notice notice-warning" role="status">
          <div className="notice-body">
            <p className="notice-title">Please add this to the chart</p>
            <p className="muted">{gapHint}</p>
            <p className="muted small">
              Form is focused on {focus || "a note"}. Save the visit, then open the patient chart.
            </p>
          </div>
        </div>
      ) : null}

      {!isPatient && (focus === "document" || /^PAT-\d{6}$/.test(selectedPatientId)) ? (
        <AttachReport
          patientId={selectedPatientId}
          caseId={caseParam || undefined}
          initialType={searchParams.get("doctype") || undefined}
          gap={focus === "document" ? gapHint : undefined}
          defaultOpen={focus === "document"}
        />
      ) : null}

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      {mode === "visit" ? (
        <form className="panel form-grid visit-form" onSubmit={onSubmitVisit}>
          {draftHint ? (
            <p className="agent-draft span-2" role="status">
              Draft applied from chart evidence — review before save. Not a diagnosis.
              {focus === "labs" || focus === "meds" || focus === "diagnoses"
                ? " Draft is in Assessment / plan below."
                : " Draft is in the visit history field."}
            </p>
          ) : null}
          <div className="span-2 extract-block" aria-label="AI document extract">
            <div className="dx-head">
              <h2 className="form-section-title">Upload lab report or prescription</h2>
            </div>
            <p className="muted">
              PDF, image, or text — AI fills labs, meds, and note fields below. Review every value.
              Nothing is saved until you click Save visit note.
            </p>
            <div className="extract-controls">
              <label className="field">
                <span>Document type</span>
                <select
                  value={extractKind}
                  onChange={(e) =>
                    setExtractKind(
                      e.target.value as "auto" | "lab_report" | "prescription" | "clinical_note",
                    )
                  }
                  disabled={extractBusy || busy}
                >
                  <option value="auto">Auto-detect</option>
                  <option value="lab_report">Lab report</option>
                  <option value="prescription">Prescription</option>
                  <option value="clinical_note">Clinical note</option>
                </select>
              </label>
              <label className="field grow">
                <span>Choose file</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.txt,.png,.jpg,.jpeg,.webp,application/pdf,image/*"
                  disabled={extractBusy || busy}
                  onChange={(e) => void onExtractFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            {extractBusy ? (
              <p className="hint" role="status">
                Extracting fields with AI…
              </p>
            ) : null}
            {extractMeta ? (
              <div className="extract-status" role="status">
                <p>
                  Filled from <strong>{extractMeta.filename || "upload"}</strong> ·{" "}
                  {extractMeta.extraction_method.replace("_", " ")}
                  {extractMeta.document_kind !== "unknown"
                    ? ` · ${extractMeta.document_kind.replaceAll("_", " ")}`
                    : ""}
                  {" · "}
                  {labRows.filter((r) => r.test_name.trim()).length} labs ·{" "}
                  {medRows.filter((r) => r.name.trim()).length} meds
                </p>
                {pendingReportFile ? (
                  <p className="hint">
                    Original file <strong>{pendingReportFile.name}</strong> will be kept on the chart when you save.
                  </p>
                ) : null}
                {extractMeta.warnings?.length ? (
                  <ul className="extract-warnings">
                    {extractMeta.warnings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">Edit any field below before saving.</p>
                )}
              </div>
            ) : null}
          </div>

          <h2 className="form-section-title span-2">Patient</h2>
          <div className="span-2 picker-block">
            {isPatient ? (
              <p className="muted small" role="status">
                Visit note writes only to your record: <strong>{myPatientId}</strong>
              </p>
            ) : (
              <>
                <label className="field">
                  <span>Find existing patient</span>
                  <input
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    placeholder="Type PAT-ID or name (2+ characters)"
                    autoComplete="off"
                  />
                </label>
                {pickerHits.length > 0 ? (
                  <ul className="picker-list">
                    {pickerHits.map((item) => (
                      <li key={item.patient_id}>
                        <button type="button" onClick={() => selectExisting(item)}>
                          <strong>{item.patient_id}</strong>
                          <span>{item.synthetic_name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {selectedPatientId ? (
                  <p className="muted small">
                    Chart linked: <strong>{selectedPatientId}</strong>
                    {displayName ? ` · ${displayName}` : ""}
                  </p>
                ) : (
                  <p className="muted small">Or enter a new MRN below to create a chart.</p>
                )}
              </>
            )}
          </div>

          <label className="field">
            <span>MRN / Patient ID</span>
            <input
              value={isPatient ? myPatientId : mrn}
              onChange={(e) => !isPatient && setMrn(e.target.value)}
              placeholder="PAT-000001 or hospital MRN"
              required
              readOnly={isPatient}
            />
          </label>
          <label className="field">
            <span>Visit number</span>
            <input value={visitNumber} onChange={(e) => setVisitNumber(e.target.value)} required />
          </label>
          <label className="field">
            <span>Hospital / facility</span>
            <input
              value={facilityName}
              onChange={(e) => setFacilityName(e.target.value)}
              placeholder="Which hospital or clinic?"
              required
            />
          </label>
          <label className="field">
            <span>Specialty / department</span>
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              aria-label="Specialty"
            >
              {(specialties.length ? specialties : [department]).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <h2 className="form-section-title span-2">Clinical</h2>
          <label className="field span-2">
            <span>Chief complaint</span>
            <input
              ref={complaintRef}
              value={chiefComplaint}
              onChange={(e) => setChiefComplaint(e.target.value)}
              placeholder="Why is the patient here?"
              required={
                !assessmentPlan.trim() &&
                !diagnoses.some((row) => row.display.trim())
              }
            />
          </label>

          {knownConditions.length > 0 ? (
            <div className="span-2">
              <p className="chip-label">Known conditions — tap to include/exclude</p>
              <div className="chip-row">
                {knownConditions.map((condition) => {
                  const active = diagnoses.some(
                    (row) => row.display.trim().toLowerCase() === condition.toLowerCase(),
                  );
                  return (
                    <button
                      key={condition}
                      type="button"
                      className={`chip${active ? " is-active" : ""}`}
                      onClick={() => toggleKnownCondition(condition)}
                    >
                      {condition}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div className="span-2 dx-block">
            <div className="dx-head">
              <h3 className="field-group-title">Diagnoses</h3>
              <button type="button" className="btn btn-secondary btn-sm" onClick={addDxRow}>
                Add another
              </button>
            </div>
            {diagnoses.map((row, index) => (
              <div className="dx-row" key={`dx-${index}`}>
                <label className="field grow">
                  <span>Disorder {index + 1}</span>
                  <input
                    value={row.display}
                    onChange={(e) => updateDx(index, { display: e.target.value })}
                    placeholder="e.g. Gingivitis (disorder)"
                  />
                </label>
                <label className="field dx-code">
                  <span>ICD-10</span>
                  <input
                    value={row.code}
                    onChange={(e) => updateDx(index, { code: e.target.value })}
                    placeholder="Optional"
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => removeDxRow(index)}
                  aria-label={`Remove diagnosis ${index + 1}`}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>

          <label className="field span-2">
            <span>Assessment / plan</span>
            <textarea
              value={assessmentPlan}
              onChange={(e) => setAssessmentPlan(e.target.value)}
              rows={2}
              placeholder="Plan and follow-up"
            />
          </label>

          <div className="span-2">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setShowMore((value) => !value)}
            >
              {showMore ? "Hide extra fields" : "Add vitals, labs, meds, demographics"}
            </button>
          </div>

          {showMore ? (
            <>
              <h2 className="form-section-title span-2">More details</h2>
              <label className="field">
                <span>Name</span>
                <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              </label>
              <label className="field">
                <span>Sex</span>
                <select value={sex} onChange={(e) => setSex(e.target.value)}>
                  <option value="unknown">Unknown</option>
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                  <option value="other">Other</option>
                </select>
              </label>
              <label className="field">
                <span>DOB</span>
                <input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
              </label>
              <label className="field">
                <span>Specialty (advanced override)</span>
                <input
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  list="specialty-options"
                />
                <datalist id="specialty-options">
                  {specialties.map((item) => (
                    <option key={item} value={item} />
                  ))}
                </datalist>
              </label>
              <label className="field span-2">
                <span>Attending</span>
                <input value={attending} onChange={(e) => setAttending(e.target.value)} />
              </label>
              <label className="field span-2">
                <span>HPI</span>
                <textarea value={hpi} onChange={(e) => setHpi(e.target.value)} rows={2} />
              </label>
              <label className="field">
                <span>BP</span>
                <input value={bp} onChange={(e) => setBp(e.target.value)} placeholder="120/80" />
              </label>
              <label className="field">
                <span>HR</span>
                <input value={hr} onChange={(e) => setHr(e.target.value)} placeholder="72" />
              </label>
              <label className="field">
                <span>Temp</span>
                <input value={temp} onChange={(e) => setTemp(e.target.value)} placeholder="36.8" />
              </label>
              <div className="span-2 dx-block">
                <div className="dx-head">
                  <h3 className="panel-title">Labs</h3>
                  <button
                    type="button"
                    className="btn btn-ghost sm"
                    onClick={() => setLabRows((rows) => [...rows, emptyLab()])}
                  >
                    Add lab
                  </button>
                </div>
                {labRows.map((row, index) => (
                  <div className="dx-row" key={`lab-${index}`}>
                    <label className="field grow">
                      <span>Test {index + 1}</span>
                      <input
                        value={row.test_name}
                        onChange={(e) =>
                          setLabRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, test_name: e.target.value } : item,
                            ),
                          )
                        }
                        placeholder="e.g. HbA1c"
                      />
                    </label>
                    <label className="field dx-code">
                      <span>Value</span>
                      <input
                        value={row.value}
                        onChange={(e) =>
                          setLabRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, value: e.target.value } : item,
                            ),
                          )
                        }
                      />
                    </label>
                    <label className="field dx-code">
                      <span>Unit</span>
                      <input
                        value={row.unit}
                        onChange={(e) =>
                          setLabRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, unit: e.target.value } : item,
                            ),
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-ghost sm"
                      onClick={() =>
                        setLabRows((rows) =>
                          rows.length <= 1 ? [emptyLab()] : rows.filter((_, i) => i !== index),
                        )
                      }
                      aria-label={`Remove lab ${index + 1}`}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>

              <div className="span-2 dx-block">
                <div className="dx-head">
                  <h3 className="panel-title">Medications</h3>
                  <button
                    type="button"
                    className="btn btn-ghost sm"
                    onClick={() => setMedRows((rows) => [...rows, emptyMed()])}
                  >
                    Add medication
                  </button>
                </div>
                {medRows.map((row, index) => (
                  <div className="dx-row" key={`med-${index}`}>
                    <label className="field grow">
                      <span>Medication {index + 1}</span>
                      <input
                        value={row.name}
                        onChange={(e) =>
                          setMedRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, name: e.target.value } : item,
                            ),
                          )
                        }
                        placeholder="e.g. Metformin"
                      />
                    </label>
                    <label className="field dx-code">
                      <span>Dose</span>
                      <input
                        value={row.dose}
                        onChange={(e) =>
                          setMedRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, dose: e.target.value } : item,
                            ),
                          )
                        }
                        placeholder="500 mg"
                      />
                    </label>
                    <label className="field dx-code">
                      <span>Freq</span>
                      <input
                        value={row.frequency}
                        onChange={(e) =>
                          setMedRows((rows) =>
                            rows.map((item, i) =>
                              i === index ? { ...item, frequency: e.target.value } : item,
                            ),
                          )
                        }
                        placeholder="BD"
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-ghost sm"
                      onClick={() =>
                        setMedRows((rows) =>
                          rows.length <= 1 ? [emptyMed()] : rows.filter((_, i) => i !== index),
                        )
                      }
                      aria-label={`Remove medication ${index + 1}`}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          <div className="span-2 insurance-opt-in">
            <label className="consent-check">
              <input
                type="checkbox"
                checked={includeInsurance}
                onChange={(e) => {
                  const on = e.target.checked;
                  setIncludeInsurance(on);
                  if (on && !policyId && policies[0]) setPolicyId(policies[0].policy_id);
                  if (!on) setPolicyId("");
                }}
              />
              <span>This visit involves insurance / cashless (optional)</span>
            </label>
            {includeInsurance ? (
              <div className="form-grid insurance-fields">
                <label className="field">
                  <span>Checklist</span>
                  <select
                    value={policyId}
                    onChange={(e) => {
                      const next = e.target.value;
                      setPolicyId(next);
                      const match = policies.find((item) => item.policy_id === next);
                      if (match && !procedure.trim()) setProcedure(match.procedure);
                    }}
                  >
                    <option value="">Select checklist…</option>
                    {policies.map((item) => (
                      <option key={item.policy_id} value={item.policy_id}>
                        {policyOptionLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Procedure</span>
                  <input
                    value={procedure}
                    onChange={(e) => setProcedure(e.target.value)}
                    placeholder="e.g. Total knee replacement"
                    required={includeInsurance}
                  />
                </label>
              </div>
            ) : (
              <p className="muted small">Skip for self-pay or routine visits — no pre-auth case is created.</p>
            )}
          </div>

          {consentRequired ? (
            <ConsentCapture
              patientId={
                isPatient
                  ? myPatientId
                  : selectedPatientId && /^PAT-\d{6}$/.test(selectedPatientId)
                    ? selectedPatientId
                    : undefined
              }
              draft={consentDraft}
              onChange={setConsentDraft}
              canRecord={!isPatient}
            />
          ) : null}
          <div className="span-2 save-bar">
            {consentRequired ? null : (
              <label className="consent-check">
                <input
                  type="checkbox"
                  checked={consentAttested}
                  onChange={(e) => setConsentAttested(e.target.checked)}
                />
                <span>
                  I confirm this visit data is synthetic or consented demonstration data (required).
                </span>
              </label>
            )}
            <button
              className="btn btn-primary"
              type="submit"
              disabled={busy || !consentReady}
            >
              {busy ? "Saving…" : "Save visit note"}
            </button>
            <span className="muted">Save attaches this visit to the patient chart.</span>
          </div>
        </form>
      ) : null}

      {mode === "fhir" ? (
        <form className="panel form-grid" onSubmit={onSubmitFhir}>
          <p className="muted span-2">
            Paste a FHIR R4 Bundle from the hospital interface. Prefer the visit form above for
            day-to-day documentation.
          </p>
          <label className="field span-2">
            <span>FHIR R4 Bundle JSON</span>
            <textarea
              className="code-area"
              value={fhirJson}
              onChange={(e) => setFhirJson(e.target.value)}
              rows={14}
              required
            />
          </label>
          <label className="field span-2 consent-check">
            <input
              type="checkbox"
              checked={includeInsurance}
              onChange={(e) => setIncludeInsurance(e.target.checked)}
            />
            <span>Also open an insurance / cashless case (optional)</span>
          </label>
          {includeInsurance ? (
            <>
              <label className="field">
                <span>Checklist</span>
                <select value={policyId} onChange={(e) => setPolicyId(e.target.value)}>
                  <option value="">Select checklist…</option>
                  {policies.map((item) => (
                    <option key={item.policy_id} value={item.policy_id}>
                      {policyOptionLabel(item)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Procedure</span>
                <input
                  value={procedure}
                  onChange={(e) => setProcedure(e.target.value)}
                  placeholder="e.g. Total knee replacement"
                  required={includeInsurance}
                />
              </label>
            </>
          ) : null}
          {consentRequired ? (
            <ConsentCapture
              patientId={
                selectedPatientId && /^PAT-\d{6}$/.test(selectedPatientId)
                  ? selectedPatientId
                  : undefined
              }
              draft={consentDraft}
              onChange={setConsentDraft}
              canRecord={!isPatient}
            />
          ) : null}
          <div className="form-actions span-2">
            {consentRequired ? null : (
              <label className="consent-check">
                <input
                  type="checkbox"
                  checked={consentAttested}
                  onChange={(e) => setConsentAttested(e.target.checked)}
                />
                <span>
                  I confirm this visit data is synthetic or consented demonstration data (required).
                </span>
              </label>
            )}
            <button className="btn btn-primary" type="submit" disabled={busy || !consentReady}>
              {busy ? "Importing…" : "Import FHIR visit"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setMode("visit")}>
              Back to visit form
            </button>
          </div>
        </form>
      ) : null}

      {!isPatient ? (
        <details
          className="panel disclosure visit-advanced"
          id="hospital-feed"
          open={advancedOpen || feedOpenInitially || undefined}
          onToggle={(event) => setAdvancedOpen((event.target as HTMLDetailsElement).open)}
        >
          <summary>
            <span className="section-title">Hospital systems</span>
            <span className="muted small">HIS feed · FHIR import · optional for integrators</span>
          </summary>
          <div className="section-bar">
            <p className="muted">
              Practice path for interface engines: a simulated HIS visit lands on the chart, and live
              push updates connected desks.
            </p>
            <p className="muted small" role="status">
              {formatLiveAge(pipeUpdatedAt, pushConnected)}
              {pipeStatus ? ` · ${pipeStatus.recent_ok}/${pipeStatus.recent_total} recent ok` : ""}
            </p>
          </div>
          <div className="button-row">
            {pipeStatus?.simulate_allowed !== false ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={pipeBusy}
                onClick={() => void onSimulateHospitalFeed()}
              >
                {pipeBusy ? "Running feed…" : "Simulate hospital visit"}
              </button>
            ) : (
              <p className="muted small" role="status">
                Live mode — use HIS/FHIR hospital feeds (simulator off).
                {pipeStatus?.phi_live ? " PHI program attested." : ""}
              </p>
            )}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={pipeBusy}
              onClick={() => refreshPipeline()}
            >
              Refresh pipeline
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setMode("fhir")}>
              Paste FHIR Bundle
            </button>
            {pipeRun?.patient_id ? (
              <Link className="btn btn-secondary" to={`/patients/${pipeRun.patient_id}`}>
                Open chart
              </Link>
            ) : null}
          </div>
          {pipeRun ? (
            <p className="muted small" role="status">
              Last run {pipeRun.status}
              {pipeRun.patient_id ? ` · ${pipeRun.patient_id}` : ""}
              {pipeRun.case_id ? ` · ${pipeRun.case_id}` : ""}
              {pipeRun.detail ? ` — ${pipeRun.detail}` : ""}
            </p>
          ) : (
            <p className="muted small">No hospital feeds yet.</p>
          )}
        </details>
      ) : null}

      {result ? (
        <div className="panel success-panel" role="status">
          <h2 className="section-title">
            {pipeRun ? "Hospital feed landed" : "Visit note saved"}
          </h2>
          <p>
            Patient <strong>{result.patient_id}</strong>
            {result.case_id ? ` · Case ${result.case_id}` : ""} — this visit is on the lifelong chart.
          </p>
          <div className="button-row">
            <Link className="btn btn-primary" to={`/patients/${result.patient_id}`}>
              Open chart
            </Link>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() =>
                printVisitSummary({
                  facilityName: facilityName || facilityLabel,
                  doctorName: attending.trim() || roleLabel,
                  roleLabel,
                  patientId: result.patient_id,
                  patientName: displayName,
                  sex,
                  dob: birthDate,
                  visitNumber,
                  department,
                  chiefComplaint,
                  hpi,
                  assessmentPlan,
                  diagnoses,
                  labName: labRows.find((row) => row.test_name.trim())?.test_name || "",
                  labValue: labRows.find((row) => row.test_name.trim())?.value || "",
                  labUnit: labRows.find((row) => row.test_name.trim())?.unit || "",
                  medName: medRows.find((row) => row.name.trim())?.name || "",
                  vitals: { bp, hr, temp },
                  caseId: result.case_id || undefined,
                })
              }
            >
              Print visit summary
            </button>
            {includeInsurance && (result.case_id || policyId) ? (
              <Link
                className="btn btn-secondary"
                to={`/patients/${result.patient_id}?${new URLSearchParams({
                  tab: "insurance",
                  prepare: "1",
                  ...(policyId ? { policy: policyId } : {}),
                  ...(result.case_id || caseParam
                    ? { case: result.case_id || caseParam }
                    : {}),
                }).toString()}`}
              >
                Open insurance tab
              </Link>
            ) : null}
            {result.case_id ? (
              <Link
                className="btn btn-secondary"
                to={`/reviews?case=${encodeURIComponent(result.case_id)}`}
              >
                Open Reviews
              </Link>
            ) : (
              <Link className="btn btn-secondary" to="/visit">
                Next patient
              </Link>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
