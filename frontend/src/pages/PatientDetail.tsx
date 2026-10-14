import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import {
  getDocument,
  getLifelongSummary,
  getPatient,
  getPatientEssentials,
  getPatientTimeline,
  getPolicies,
  preparePacket,
  type EvidencePacket,
  type LifelongSummary,
  type PatientDetail,
  type PatientEssentials,
  type PolicySummary,
  type TimelineEvent,
} from "../api";
import { getDeskWorklist, isEndpointMissing, type WorklistItem } from "../deskApi";
import {
  clinicalConditions,
  criterionStatusLabel,
  essentialsStatusLabel,
  noteTypeLabel,
  policyOptionLabel,
} from "../labels";
import { printEvidencePacket } from "../printSheet";
import { pushRecentPatient } from "../recentPatients";
import { useRole } from "../roleContext";
import {
  Button,
  ButtonLink,
  ClockChip,
  EmptyState,
  Icon,
  ItemStatusPill,
  Notice,
  ReadinessMeter,
  Skeleton,
  StagePill,
  StatusPill,
  Tabs,
  ageFromDob,
  formatDate,
  formatDateTime,
} from "../ui";

type ChartTab = "file" | "notes" | "labs" | "meds" | "imaging" | "procedures";
const CHART_TABS: ChartTab[] = ["file", "notes", "labs", "meds", "imaging", "procedures"];

const TYPE_LABELS: Record<string, string> = {
  clinical_note: "Note",
  lab_result: "Lab",
  medication: "Medication",
  procedure: "Procedure",
  imaging_study: "Imaging",
  claim: "Claim",
};

function visitHref(patientId: string, gap: { label: string; focus: string; specialty_hint?: string; draft_suggestion?: string }): string {
  const params = new URLSearchParams({ patient: patientId, focus: gap.focus, gap: gap.label });
  if (gap.specialty_hint) params.set("specialty", gap.specialty_hint);
  if (gap.draft_suggestion) params.set("draft", gap.draft_suggestion.slice(0, 800));
  return `/visit?${params.toString()}`;
}

function essentialsHref(patientId: string, section: { key: string; label: string; action: string }): string {
  const focus =
    section.key === "labs" ? "labs" : section.key === "medications" ? "meds" : section.key === "conditions" ? "diagnoses" : "note";
  const specialty = focus === "labs" ? "Laboratory" : focus === "meds" ? "Pharmacy" : "General medicine";
  return visitHref(patientId, { label: section.action || section.label, focus, specialty_hint: specialty });
}

/** Map a legacy packet criterion status onto the one checklist vocabulary. */
function packetStatus(status: string): "SUPPORTED" | "MISSING" | "UNKNOWN" | "NOT_SUPPORTED" {
  const value = status.toUpperCase();
  return value === "SUPPORTED" || value === "MISSING" || value === "NOT_SUPPORTED" ? value : "UNKNOWN";
}

export function PatientDetailPage() {
  const { patientId = "" } = useParams();
  const { canPrepare, canDocument, isPatient, myPatientId, setMyPatientId, label: roleLabel, facilityLabel } = useRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [policyId, setPolicyId] = useState("POL-000001");
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [essentials, setEssentials] = useState<PatientEssentials | null>(null);
  const [lifelong, setLifelong] = useState<LifelongSummary | null>(null);
  const [cases, setCases] = useState<WorklistItem[] | null>(null);
  const [deskMissing, setDeskMissing] = useState(false);
  const [prepBusy, setPrepBusy] = useState(false);
  const [error, setError] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [source, setSource] = useState<{ id: string; content: string } | null>(null);
  const [sourceBusy, setSourceBusy] = useState(false);

  const blocked = isPatient && Boolean(patientId) && patientId.toUpperCase() !== myPatientId;
  const tabParam = searchParams.get("tab") || "";
  const tab: ChartTab = (CHART_TABS as string[]).includes(tabParam) ? (tabParam as ChartTab) : "file";
  const autoPrepare = searchParams.get("prepare") === "1";
  const policyParam = searchParams.get("policy") || "";
  const caseParam = searchParams.get("case") || "";

  useEffect(() => {
    if (blocked) return;
    let cancelled = false;
    setPatient(null);
    setTimeline([]);
    setPacket(null);
    setEssentials(null);
    setLifelong(null);
    setCases(null);
    setError("");
    setSpecialtyFilter("all");
    setExpandedId(null);
    setSource(null);
    Promise.all([
      getPatient(patientId),
      getPatientTimeline(patientId),
      getPolicies().catch(() => ({ policies: [] as PolicySummary[], total: 0 })),
      getPatientEssentials(patientId).catch(() => null),
      getLifelongSummary(patientId).catch(() => null),
    ])
      .then(([body, feed, policyBody, essentialsBody, lifelongBody]) => {
        if (cancelled) return;
        setPatient(body);
        setTimeline(feed.events);
        setPolicies(policyBody.policies);
        setEssentials(essentialsBody);
        setLifelong(lifelongBody);
        const preferred =
          policyBody.policies.find((item) => item.policy_id === policyParam) ??
          policyBody.policies.find((item) => item.policy_id === "POL-000001") ??
          policyBody.policies[0];
        if (preferred) setPolicyId(preferred.policy_id);
        pushRecentPatient({ patient_id: body.patient_id, display_name: body.demographics.synthetic_name });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open this chart.");
      });
    if (!isPatient) {
      getDeskWorklist({ q: patientId, limit: 50 })
        .then((body) => {
          if (!cancelled) setCases(body.items.filter((item) => item.patient_id === patientId));
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setCases([]);
          setDeskMissing(isEndpointMissing(err));
        });
    } else {
      setCases([]);
    }
    return () => {
      cancelled = true;
    };
  }, [patientId, policyParam, isPatient, blocked]);

  const conditions = useMemo(() => clinicalConditions(patient?.conditions ?? []), [patient]);
  const specialties = useMemo(() => {
    const values = new Set<string>();
    for (const event of timeline) if (event.specialty) values.add(event.specialty);
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [timeline]);
  const visibleEvents = useMemo(
    () => (specialtyFilter === "all" ? timeline : timeline.filter((event) => event.specialty === specialtyFilter)),
    [timeline, specialtyFilter],
  );

  const hasDeskCase = (cases ?? []).length > 0;
  const selectedPolicy = policies.find((item) => item.policy_id === policyId) ?? null;

  async function runPrepare() {
    if (!patient || !policyId) return;
    setPrepBusy(true);
    setError("");
    try {
      setPacket(
        await preparePacket({
          patient_id: patient.patient_id,
          policy_id: policyId,
          procedure: selectedPolicy?.procedure,
          case_id: caseParam || undefined,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare the evidence pack.");
    } finally {
      setPrepBusy(false);
    }
  }

  useEffect(() => {
    if (!autoPrepare || !patient || !policyId || prepBusy || packet || cases === null || hasDeskCase) return;
    void runPrepare();
    // Auto-run once when deep-linked with ?prepare=1 and no desk case exists.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPrepare, patient, policyId, cases]);

  function setTab(next: ChartTab) {
    const params = new URLSearchParams(searchParams);
    if (next === "file") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  function printPacket() {
    if (!packet || !patient) return;
    printEvidencePacket({
      facilityLabel,
      doctorName: roleLabel,
      roleLabel,
      patientId: packet.patient_id,
      patientName: patient.demographics.synthetic_name,
      caseId: packet.case_id,
      policyTitle: packet.policy_title,
      procedure: packet.procedure,
      readinessPercent: packet.readiness_percent,
      gapCount: packet.gap_count,
      humanReviewRequired: packet.human_review_required,
      criteria: packet.criteria.map((item) => ({
        plain_status: item.plain_status || criterionStatusLabel(item.status),
        criterion: item.criterion,
      })),
      gaps: packet.gaps.map((gap) => ({ label: gap.label, action: gap.action })),
      nextSteps: packet.next_steps,
      packetSummary: packet.packet_summary,
      disclaimer: packet.disclaimer,
    });
  }

  async function openSource(documentId: string) {
    setSourceBusy(true);
    try {
      const document = await getDocument(documentId);
      setSource({ id: documentId, content: document.content });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the document.");
    } finally {
      setSourceBusy(false);
    }
  }

  if (blocked) {
    return <Navigate to={`/patients/${myPatientId}`} replace />;
  }

  if (error && !patient) {
    return (
      <section className="page">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link to="/patients">Patients</Link>
        </nav>
        <Notice tone="danger" title="Could not open this chart">
          {error}
        </Notice>
      </section>
    );
  }

  if (!patient) {
    return (
      <section className="page">
        <Skeleton lines={6} label="Loading patient chart" />
      </section>
    );
  }

  const age = ageFromDob(patient.demographics.date_of_birth);
  const gaps = essentials?.sections.filter((s) => s.status === "missing" || s.status === "thin" || s.status === "unknown") ?? [];

  return (
    <section className="page chart-page">
      {!isPatient ? (
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link to="/patients">Patients</Link>
          <Icon name="arrow-right" size={12} />
          <span aria-current="page">{patient.patient_id}</span>
        </nav>
      ) : null}

      <header className="chart-head">
        <div>
          <h1 className="page-title chart-name">{patient.demographics.synthetic_name}</h1>
          <dl className="chart-facts">
            <div>
              <dt>ID</dt>
              <dd className="num">{patient.patient_id}</dd>
            </div>
            <div>
              <dt>Age</dt>
              <dd>{age != null ? `${age} years` : "—"}</dd>
            </div>
            <div>
              <dt>Sex</dt>
              <dd className="capitalize">{patient.demographics.sex || "—"}</dd>
            </div>
            <div>
              <dt>Date of birth</dt>
              <dd>{formatDate(patient.demographics.date_of_birth)}</dd>
            </div>
          </dl>
          <div className="chip-row" aria-label="Conditions">
            {conditions.length === 0 ? <span className="muted small">No conditions recorded</span> : null}
            {conditions.slice(0, 6).map((condition) => (
              <span key={condition} className="chip chip-static">
                {condition}
              </span>
            ))}
            {conditions.length > 6 ? <span className="muted small">+{conditions.length - 6} more</span> : null}
          </div>
        </div>
        <div className="button-row">
          {canDocument ? (
            <ButtonLink to={`/visit?patient=${encodeURIComponent(patient.patient_id)}`} icon="note">
              Add visit note
            </ButtonLink>
          ) : null}
        </div>
      </header>

      {error ? <Notice tone="danger">{error}</Notice> : null}

      <section className="panel packet-panel" id="evidence-packet" aria-labelledby="packet-title">
        <div className="section-bar">
          <h2 className="section-title" id="packet-title">
            Evidence pack
          </h2>
          {!hasDeskCase && canPrepare && cases !== null ? (
            <div className="button-row">
              {policies.length > 1 ? (
                <label className="inline-field">
                  <span className="sr-only">Checklist</span>
                  <select
                    value={policyId}
                    onChange={(event) => {
                      setPolicyId(event.target.value);
                      setPacket(null);
                    }}
                  >
                    {policies.map((item) => (
                      <option key={item.policy_id} value={item.policy_id}>
                        {policyOptionLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <Button variant="primary" size="sm" loading={prepBusy} disabled={!policyId} onClick={() => void runPrepare()}>
                {packet ? "Re-check evidence pack" : "Prepare evidence pack"}
              </Button>
            </div>
          ) : null}
        </div>

        {hasDeskCase ? (
          <>
            <p className="muted small">
              One readiness number per case: required checklist items supported by the chart.
            </p>
            <ul className="case-rows">
              {(cases ?? []).map((item) => (
                <li key={item.case_id}>
                  <Link className="case-row" to={`/cases/${encodeURIComponent(item.case_id)}`}>
                    <span className="case-row-main">
                      <strong>{item.proposed_treatment || item.case_id}</strong>
                      <span className="muted small">
                        {item.case_id}
                        {item.insurer_name ? `, ${item.insurer_name}` : ""}
                        {item.tpa_name ? ` via ${item.tpa_name}` : ""}
                      </span>
                    </span>
                    <StagePill stage={item.stage} fallbackLabel={item.stage_label} />
                    <span className="num">
                      {Math.round(item.readiness_percent)}% ready
                      {item.open_items ? <span className="muted small">, {item.open_items} open</span> : null}
                    </span>
                    <ClockChip clock={item.clock} />
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : packet ? (
          <div className="packet-result">
            <ReadinessMeter
              percent={packet.readiness_percent}
              label={`${packet.supported_count} supported, ${packet.gap_count} open item${packet.gap_count === 1 ? "" : "s"}`}
            />
            {packet.gaps.length > 0 ? (
              <ul className="gap-list">
                {packet.gaps.map((gap) => (
                  <li key={`${gap.focus}-${gap.label}`}>
                    <span>{gap.label}</span>
                    <ButtonLink size="sm" to={visitHref(packet.patient_id, gap)}>
                      {gap.draft_suggestion ? "Use draft in visit note" : "Add to chart"}
                    </ButtonLink>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Nothing left open on this checklist.</p>
            )}
            <details className="disclosure">
              <summary>Full checklist ({packet.criteria.length} items)</summary>
              <ul className="check-list compact">
                {packet.criteria.map((item) => (
                  <li key={item.criterion_id} className="check-item">
                    <div className="check-head">
                      <ItemStatusPill status={packetStatus(item.status)} />
                      <p className="check-label">{item.criterion}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
            <div className="button-row">
              <Button size="sm" icon="print" onClick={printPacket}>
                Print / Save PDF
              </Button>
              {packet.human_review_required ? (
                <ButtonLink size="sm" to={`/reviews?case=${encodeURIComponent(packet.case_id)}&queue=open`}>
                  Open in Reviews
                </ButtonLink>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="muted">
            {canPrepare
              ? deskMissing
                ? "Case tracking is not available on this server yet. You can still check the chart against a pre-auth checklist."
                : "No cashless case is open for this patient. Check the chart against a pre-auth checklist to see what is still missing."
              : "Preparing an evidence pack needs a care-team sign-in."}
          </p>
        )}
      </section>

      {gaps.length > 0 ? (
        <section className="panel" aria-labelledby="gaps-title">
          <h2 className="section-title" id="gaps-title">
            Chart gaps
          </h2>
          <ul className="gap-list">
            {gaps.map((section) => (
              <li key={section.key}>
                <span>
                  <strong>{section.label}</strong>{" "}
                  <StatusPill
                    tone={section.status === "missing" ? "danger" : "warning"}
                    label={essentialsStatusLabel(section.status)}
                  />
                  <span className="muted small"> {section.action}</span>
                </span>
                {canDocument ? (
                  <ButtonLink size="sm" to={essentialsHref(patient.patient_id, section)}>
                    Add to chart
                  </ButtonLink>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {lifelong ? (
        <details className="panel disclosure lifelong" id="lifelong-history">
          <summary>
            <span className="section-title">Lifelong history</span>
            <span className="muted small">{lifelong.events.length} past events</span>
          </summary>
          {lifelong.includes_demo_synthetic ? (
            <Notice tone="warning" title="Demo history">
              {lifelong.demo_synthetic_disclaimer ||
                "Some events below are invented examples, not from this patient's chart. Do not use them for care or insurance decisions."}
            </Notice>
          ) : null}
          {lifelong.doctor_brief ? <p className="muted">{lifelong.doctor_brief}</p> : null}
          <ul className="event-list">
            {lifelong.events.slice(0, 8).map((event) => (
              <li key={event.event_id}>
                <span className="event-when">{event.occurred_on ? event.occurred_on.slice(0, 4) : "—"}</span>
                <div>
                  <p>
                    <strong>{event.title}</strong> <span className="muted small">{event.category}</span>
                    {event.demo_synthetic && lifelong.events.some((item) => !item.demo_synthetic) ? (
                      <span className="tag">Example</span>
                    ) : null}
                  </p>
                  <p className="muted small">{event.summary}</p>
                </div>
              </li>
            ))}
          </ul>
          <p>
            {isPatient ? (
              <Link to="/my-record">Open my full record</Link>
            ) : (
              <Link
                to={`/my-record?patient=${encodeURIComponent(patient.patient_id)}`}
                onClick={() => setMyPatientId(patient.patient_id)}
              >
                Open the full lifelong record
              </Link>
            )}
          </p>
        </details>
      ) : null}

      <section className="chart-file" aria-labelledby="chart-file-title">
        <h2 className="section-title" id="chart-file-title">
          Chart file
        </h2>
        <Tabs
          items={[
            { id: "file", label: "All records", count: timeline.length },
            { id: "notes", label: "Notes", count: patient.clinical_notes.length },
            { id: "labs", label: "Labs", count: patient.labs.length },
            { id: "meds", label: "Medications", count: patient.medications.length },
            { id: "imaging", label: "Imaging", count: patient.imaging.length },
            { id: "procedures", label: "Procedures", count: patient.procedures.length },
          ]}
          active={tab}
          onChange={setTab}
          label="Chart sections"
          idPrefix="chart"
        />
        <div id="chart-panel" role="tabpanel" aria-labelledby={`chart-tab-${tab}`} className="panel tab-panel">
          {tab === "file" ? (
            <>
              {specialties.length > 1 ? (
                <div className="chip-row" aria-label="Specialty filter">
                  {["all", ...specialties].map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={`chip${specialtyFilter === value ? " is-active" : ""}`}
                      aria-pressed={specialtyFilter === value}
                      onClick={() => setSpecialtyFilter(value)}
                    >
                      {value === "all" ? "All specialties" : value}
                    </button>
                  ))}
                </div>
              ) : null}
              {visibleEvents.length === 0 ? (
                <EmptyState icon="doc" title="No records yet" />
              ) : (
                <ol className="record-list">
                  {visibleEvents.map((event) => {
                    const open = expandedId === event.event_id;
                    return (
                      <li key={event.event_id} className={open ? "is-open" : undefined}>
                        <button
                          type="button"
                          className="record-toggle"
                          aria-expanded={open}
                          onClick={() => setExpandedId(open ? null : event.event_id)}
                        >
                          <span className="record-when">{formatDateTime(event.timestamp)}</span>
                          <span className="record-type">{TYPE_LABELS[event.event_type] || event.event_type}</span>
                          <span className="record-title">{event.title || event.event_id}</span>
                          <span className="muted small">{event.specialty || "General medicine"}</span>
                          <Icon name="chevron-down" className="record-chevron" />
                        </button>
                        {open ? (
                          <div className="record-body">
                            <p>{event.description}</p>
                            {event.document_id ? (
                              <Button size="sm" loading={sourceBusy} onClick={() => void openSource(event.document_id || "")}>
                                Open document
                              </Button>
                            ) : null}
                            {source && source.id === event.document_id ? (
                              <pre className="source-text">{source.content}</pre>
                            ) : null}
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          ) : null}
          {tab === "notes" ? (
            patient.clinical_notes.length === 0 ? (
              <EmptyState icon="note" title="No notes recorded" />
            ) : (
              <div className="note-list">
                {patient.clinical_notes.map((note) => (
                  <article key={note.note_id} className="note-block">
                    <p className="muted small">
                      {noteTypeLabel(note.note_type)}, {formatDateTime(note.authored_at)}
                    </p>
                    <pre className="source-text">{note.content}</pre>
                  </article>
                ))}
              </div>
            )
          ) : null}
          {tab === "labs" ? (
            <SimpleList
              empty="No lab results recorded"
              rows={patient.labs.map((item) => ({
                id: item.lab_id,
                main: `${item.test_name}: ${item.value} ${item.unit}`,
                when: formatDateTime(item.collected_at),
              }))}
            />
          ) : null}
          {tab === "meds" ? (
            <SimpleList
              empty="No medications recorded"
              rows={patient.medications.map((item) => ({
                id: item.medication_id,
                main: item.name,
                when: [item.dose, item.status].filter(Boolean).join(", "),
              }))}
            />
          ) : null}
          {tab === "imaging" ? (
            <SimpleList
              empty="No imaging recorded"
              rows={patient.imaging.map((study) => ({
                id: study.imaging_id,
                main: `${study.modality}, ${study.body_part}: ${study.description}`,
                when: formatDate(study.study_date),
              }))}
            />
          ) : null}
          {tab === "procedures" ? (
            <SimpleList
              empty="No procedures recorded"
              rows={patient.procedures.map((item) => ({
                id: item.procedure_id,
                main: item.name,
                when: formatDate(item.performed_at),
              }))}
            />
          ) : null}
        </div>
      </section>
    </section>
  );
}

function SimpleList({ rows, empty }: { rows: { id: string; main: string; when: string }[]; empty: string }) {
  if (rows.length === 0) {
    return <EmptyState icon="doc" title={empty} />;
  }
  return (
    <ul className="simple-list">
      {rows.map((row) => (
        <li key={row.id}>
          <span>{row.main}</span>
          <span className="muted small">{row.when}</span>
        </li>
      ))}
    </ul>
  );
}
