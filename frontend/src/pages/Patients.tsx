import { KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getPatients, type PatientSummary } from "../api";
import { getDeskWorklist, type WorklistItem } from "../deskApi";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { useI18n } from "../i18n";
import { pushRecentPatient, readRecentPatients } from "../recentPatients";
import {
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  Icon,
  Notice,
  StagePill,
  ageFromDob,
  ageSex,
  formatDate,
  useIsPhone,
  type Column,
} from "../ui";

const PAGE_SIZE = 20;

/** Latest active case per patient, from the desk worklist (if the desk API is deployed). */
function latestCaseByPatient(items: WorklistItem[]): Map<string, WorklistItem> {
  const map = new Map<string, WorklistItem>();
  for (const item of items) {
    const current = map.get(item.patient_id);
    if (!current || (item.stage !== "closed" && (current.stage === "closed" || item.updated_at > current.updated_at))) {
      map.set(item.patient_id, item);
    }
  }
  return map;
}

export function PatientsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const isPhone = useIsPhone();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [patients, setPatients] = useState<PatientSummary[] | null>(null);
  const [cases, setCases] = useState<Map<string, WorklistItem>>(new Map());
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState(() => readRecentPatients());

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setOffset(0);
  }, [debounced]);

  const loadPatients = useCallback(async () => {
    try {
      const [body, worklist] = await Promise.all([
        getPatients({ limit: PAGE_SIZE, offset, q: debounced || undefined }),
        getDeskWorklist({ limit: 200 }).catch(() => null),
      ]);
      setPatients(body.patients);
      setTotal(body.total);
      if (worklist) setCases(latestCaseByPatient(worklist.items));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load patients.");
    }
  }, [debounced, offset]);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(loadPatients, { intervalMs: 60_000 });

  useEffect(() => {
    void loadPatients();
  }, [loadPatients]);

  function remember(patient: PatientSummary) {
    try {
      pushRecentPatient({ patient_id: patient.patient_id, display_name: patient.synthetic_name });
    } catch {
      /* storage unavailable */
    }
    setRecent(readRecentPatients());
  }

  function openPatient(patient: PatientSummary) {
    remember(patient);
    navigate(`/patients/${patient.patient_id}`);
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && patients && patients.length > 0) {
      event.preventDefault();
      openPatient(patients[0]);
    }
  }

  const columns: Column<PatientSummary>[] = [
    {
      key: "mrn",
      header: t("col.mrn"),
      nowrap: true,
      render: (row) => <span className="num">{mrnOf(row)}</span>,
    },
    {
      key: "name",
      header: t("col.patient"),
      render: (row) => (
        <div className="cell-stack">
          <Link className="cell-primary row-link" to={`/patients/${row.patient_id}`} onClick={() => remember(row)}>
            {row.synthetic_name}
          </Link>
          <span className="cell-secondary">{row.patient_id}</span>
        </div>
      ),
    },
    {
      key: "agesex",
      header: t("col.ageSex"),
      nowrap: true,
      render: (row) => ageSex(ageFromDob(row.date_of_birth), row.sex),
    },
    {
      key: "stage",
      header: t("col.activeCase"),
      render: (row) => {
        const item = cases.get(row.patient_id);
        if (!item) return <span className="muted">No open case</span>;
        return (
          <div className="cell-stack">
            <Link to={`/cases/${encodeURIComponent(item.case_id)}`} className="pill-link">
              <StagePill stage={item.stage} fallbackLabel={item.stage_label} />
            </Link>
            <span className="cell-secondary">{item.proposed_treatment || item.case_id}</span>
          </div>
        );
      },
    },
    {
      key: "insurer",
      header: t("col.payer"),
      render: (row) => {
        const item = cases.get(row.patient_id);
        if (!item) return <span className="muted">—</span>;
        return (
          <div className="cell-stack">
            <span className="cell-primary-text">{item.insurer_name || "—"}</span>
            {item.tpa_name ? <span className="cell-secondary">via {item.tpa_name}</span> : null}
          </div>
        );
      },
    },
    {
      key: "last",
      header: t("col.lastVisit"),
      nowrap: true,
      render: (row) => (row.last_visit_at ? formatDate(row.last_visit_at) : <span className="muted">—</span>),
    },
  ];

  function mrnOf(row: PatientSummary): string {
    return row.mrn || cases.get(row.patient_id)?.mrn || row.patient_id;
  }

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const caption =
    patients === null
      ? "Loading patients"
      : `Showing ${pageStart}–${pageEnd} of ${total}${debounced ? ` for “${debounced}”` : ""}`;
  const emptyState = (
    <EmptyState
      icon="users"
      title={debounced ? `No patients match “${debounced}”` : "No patients on file yet"}
      action={
        debounced ? (
          <Button size="sm" onClick={() => setQuery("")}>
            Clear search
          </Button>
        ) : (
          <ButtonLink size="sm" to="/visit">
            Add visit note
          </ButtonLink>
        )
      }
    >
      {debounced ? "Check the spelling, or search by PAT-ID." : "Add a visit note to create the first chart."}
    </EmptyState>
  );

  return (
    <section className="page page-wide">
      <header className="page-head page-head-inline">
        <h1 className="page-title">Patients</h1>
        <div className="page-actions">
          <label className="search">
            <Icon name="search" />
            <span className="sr-only">Find patient</span>
            <input
              ref={searchRef}
              type="search"
              placeholder="Name, PAT-ID or MRN…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onSearchKeyDown}
              autoComplete="off"
            />
          </label>
          <ButtonLink to="/visit" variant="primary" icon="note">
            Add visit note
          </ButtonLink>
        </div>
      </header>
      <p className="page-sub page-sub-below">
        Find a patient by name, ID or MRN. Press Enter to open the first match.
        <span className="live-stamp">
          {formatLiveAge(lastUpdatedAt, pushConnected, t)}
          <button type="button" className="text-link" onClick={refreshNow}>
            {t("common.refresh")}
          </button>
        </span>
      </p>

      {recent.length > 0 && !debounced ? (
        <div className="chip-row" aria-label="Recently opened">
          <span className="chip-label">Recent</span>
          {recent.map((item) => (
            <Link key={item.patient_id} className="chip" to={`/patients/${item.patient_id}`}>
              {item.display_name || item.patient_id}
            </Link>
          ))}
        </div>
      ) : null}

      {error ? (
        <Notice
          tone="danger"
          title="Could not load patients"
          action={
            <Button size="sm" onClick={refreshNow}>
              {t("common.retry")}
            </Button>
          }
        >
          {error}
        </Notice>
      ) : isPhone ? (
        patients === null ? (
          <p className="muted" role="status">
            Loading patients
          </p>
        ) : patients.length === 0 ? (
          emptyState
        ) : (
          <>
            <ul className="card-list" aria-label="Patients">
              {patients.map((row) => {
                const item = cases.get(row.patient_id);
                return (
                  <li key={row.patient_id}>
                    <Link
                      className="list-card"
                      to={`/patients/${row.patient_id}`}
                      onClick={() => remember(row)}
                      aria-label={`Open chart for ${row.synthetic_name}`}
                    >
                      <span className="list-card-line">
                        <strong className="list-card-title">{row.synthetic_name}</strong>
                        <span className="list-card-meta num">{mrnOf(row)}</span>
                      </span>
                      <span className="list-card-line list-card-sub">
                        <span>{ageSex(ageFromDob(row.date_of_birth), row.sex)}</span>
                        <span className="muted">
                          {row.last_visit_at ? `${t("col.lastVisit")}: ${formatDate(row.last_visit_at)}` : ""}
                        </span>
                      </span>
                      {item ? (
                        <span className="list-card-line">
                          <StagePill stage={item.stage} fallbackLabel={item.stage_label} />
                          <span className="list-card-meta">{item.proposed_treatment || item.case_id}</span>
                        </span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
            <p className="muted small">{caption}</p>
          </>
        )
      ) : (
        <DataTable
          columns={columns}
          rows={patients ?? []}
          rowKey={(row) => row.patient_id}
          loading={patients === null}
          caption={caption}
          onRowActivate={openPatient}
          rowLabel={(row) => `Open chart for ${row.synthetic_name}`}
          empty={emptyState}
        />
      )}

      {patients && total > PAGE_SIZE ? (
        <div className="pager">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>
            {t("common.previous")}
          </Button>
          <span className="muted">
            Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </span>
          <Button size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset((value) => value + PAGE_SIZE)}>
            {t("common.next")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
