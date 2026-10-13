import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  getPatients,
  getWorklist,
  type Worklist,
  type WorklistCase,
} from "../api";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { procedureDisplayName } from "../labels";
import { readRecentPatients } from "../recentPatients";
import { useRole, type DeskRole, type FacilityType } from "../roleContext";

function prepareHref(item: {
  patient_id: string;
  policy_id?: string;
  case_id?: string;
}): string {
  const params = new URLSearchParams({ prepare: "1" });
  if (item.policy_id) {
    params.set("policy", item.policy_id);
  }
  if (item.case_id) {
    params.set("case", item.case_id);
  }
  return `/patients/${item.patient_id}?${params.toString()}`;
}

function visitHref(item: WorklistCase): string {
  const params = new URLSearchParams({ patient: item.patient_id });
  if (item.gap_focus) {
    params.set("focus", item.gap_focus);
  }
  if (item.gap_label) {
    params.set("gap", item.gap_label);
  }
  if (item.specialty_hint) {
    params.set("specialty", item.specialty_hint);
  }
  if (item.policy_id) {
    params.set("policy", item.policy_id);
  }
  if (item.case_id) {
    params.set("case", item.case_id);
  }
  return `/visit?${params.toString()}`;
}

function clinicianHref(item: WorklistCase): string {
  return `/reviews?case=${encodeURIComponent(item.case_id)}&queue=ready_for_human`;
}

function deskCopy(
  role: DeskRole,
  facility: FacilityType,
): { title: string; subtitle: string } {
  const rural = facility === "phc" || facility === "chc" || facility === "taluk" || facility === "district";
  switch (role) {
    case "senior_clinician":
      return {
        title: "Today",
        subtitle: rural
          ? "Confirm chart citations before cashless / referral handoff — not an approval."
          : "Consultant review of evidence packs — citations only, not coverage decisions.",
      };
    case "resident":
      return {
        title: "Today",
        subtitle: rural
          ? "Close documentation gaps and prepare packs for senior MO / consultant."
          : "PG desk: prepare packs and flag open items for unit consultant.",
      };
    case "admin":
      return {
        title: "Today",
        subtitle: "Facility queue, SLA, and org scope across OPD / referral desks.",
      };
    case "staff":
    default:
      return {
        title: "Today",
        subtitle: rural
          ? "Assemble notes from this facility and hand a clear pack for senior / referral review."
          : "Assemble chart evidence for cashless / TPA checklists; hand off for consultant review.",
      };
  }
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { role, facility, label, facilityLabel, isSenior, isResident, isStaff, canAdjudicate } =
    useRole();
  const [worklist, setWorklist] = useState<Worklist | null>(null);
  const [jump, setJump] = useState("");
  const [error, setError] = useState("");
  const [jumpError, setJumpError] = useState("");
  const [tick, setTick] = useState(0);
  const browserRecent = readRecentPatients();
  const copy = deskCopy(role, facility);

  const loadDesk = useCallback(async () => {
    try {
      const nextWorklist = await getWorklist();
      setWorklist(nextWorklist);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh Today");
    }
  }, []);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(loadDesk, {
    intervalMs: 60_000,
    enabled: true,
  });

  useEffect(() => {
    void loadDesk();
  }, [role, loadDesk]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 5_000);
    return () => window.clearInterval(id);
  }, []);
  void tick;

  const myCases = useMemo(() => worklist?.my_cases || [], [worklist]);
  const clinicianCases = useMemo(() => {
    const mine = new Set(myCases.map((item) => item.case_id));
    const ready = (worklist?.open_cases || []).filter((item) => item.status === "ready_for_human");
    const ordered = [
      ...ready.filter((item) => mine.has(item.case_id)),
      ...ready.filter((item) => !mine.has(item.case_id)),
    ];
    return ordered.sort((a, b) => Number(Boolean(b.sla_breached)) - Number(Boolean(a.sla_breached)));
  }, [worklist, myCases]);
  const staffDocCases = useMemo(() => {
    const docs = (worklist?.open_cases || []).filter(
      (item) => item.status === "needs_documentation",
    );
    return docs.sort(
      (a, b) => Number(Boolean(b.sla_breached)) - Number(Boolean(a.sla_breached)),
    );
  }, [worklist]);
  const queuedCases = useMemo(
    () =>
      (worklist?.open_cases || []).filter(
        (item) => item.status !== "ready_for_human" && item.status !== "needs_documentation",
      ),
    [worklist],
  );

  const primaryLane: "review" | "docs" =
    isStaff && !isSenior && !isResident ? "docs" : "review";

  async function onJump(event: FormEvent) {
    event.preventDefault();
    const q = jump.trim();
    if (!q) return;
    setJumpError("");
    try {
      if (/^PAT-\d{6}$/i.test(q)) {
        navigate(`/patients/${q.toUpperCase()}`);
        return;
      }
      const body = await getPatients({ limit: 1, q });
      if (body.patients[0]) {
        navigate(`/patients/${body.patients[0].patient_id}`);
        return;
      }
      setJumpError(`No patient found for “${q}”.`);
    } catch (err) {
      setJumpError(err instanceof Error ? err.message : "Lookup failed");
    }
  }

  const reviewLane = (
    <section
      className={`lane lane-senior ${primaryLane === "review" ? "lane-primary" : "lane-secondary"}`}
      aria-labelledby="lane-senior-title"
    >
      <header className="lane-head">
        <div>
          <h2 className="lane-title" id="lane-senior-title">
            {canAdjudicate ? "Needs your review" : "Needs clinician review"}
            <span className="lane-count">{clinicianCases.length}</span>
          </h2>
        </div>
        <Link className="btn btn-primary sm" to="/reviews?queue=ready_for_human">
          Open Reviews
        </Link>
      </header>

      {clinicianCases.length === 0 ? (
        <div className="lane-empty">
          <p>No evidence packs waiting for a clinician.</p>
          <Link className="btn btn-ghost sm" to="/patients">
            Open charts
          </Link>
        </div>
      ) : (
        <ul className="lane-list">
          {clinicianCases.map((item) => (
            <li key={item.case_id}>
              <Link className="lane-item" to={clinicianHref(item)}>
                <span className="lane-item-main">
                  <strong>{procedureDisplayName(item.procedure)}</strong>
                  <span className="muted">
                    {item.patient_id}
                    {item.policy_title && !/catalog|dynamic/i.test(item.policy_title)
                      ? ` · ${item.policy_title}`
                      : ""}
                    {item.cycle_elapsed_minutes != null
                      ? ` · ${item.cycle_elapsed_minutes}m open`
                      : ""}
                  </span>
                  {item.sla_breached ? (
                    <span className="badge bad sla-chip">SLA overdue</span>
                  ) : null}
                </span>
                <span className="lane-cta">
                  {canAdjudicate ? "Review evidence pack" : "Check evidence pack"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );

  const docsLane = (
    <section
      className={`lane lane-staff ${primaryLane === "docs" ? "lane-primary" : "lane-secondary"}`}
      aria-labelledby="lane-staff-title"
    >
      <header className="lane-head">
        <div>
          <h2 className="lane-title" id="lane-staff-title">
            Notes still needed
            <span className="lane-count">{staffDocCases.length}</span>
          </h2>
        </div>
        <Link className="btn btn-ghost sm" to="/patients">
          Charts
        </Link>
      </header>

      {staffDocCases.length === 0 ? (
        <div className="lane-empty">
          <p>No open items waiting for a visit note.</p>
          <div className="home-actions">
            <Link className="btn btn-ghost sm" to="/visit">
              Add visit note
            </Link>
            <Link className="btn btn-ghost sm" to="/visit#hospital-feed">
              Hospital feed
            </Link>
          </div>
        </div>
      ) : (
        <ul className="lane-list">
          {staffDocCases.map((item) => (
            <li key={item.case_id}>
              <Link className="lane-item" to={visitHref(item)}>
                <span className="lane-item-main">
                  <strong>{procedureDisplayName(item.procedure)}</strong>
                  <span className="muted">
                    {item.patient_id}
                    {item.policy_title && !/catalog|dynamic/i.test(item.policy_title)
                      ? ` · ${item.policy_title}`
                      : ""}
                    {item.cycle_elapsed_minutes != null
                      ? ` · ${item.cycle_elapsed_minutes}m open`
                      : ""}
                  </span>
                  {item.sla_breached ? (
                    <span className="badge bad sla-chip">SLA overdue</span>
                  ) : null}
                </span>
                <span className="lane-cta">Add visit note</span>
              </Link>
              <Link className="lane-secondary" to={prepareHref(item)}>
                Re-check evidence pack
              </Link>
            </li>
          ))}
        </ul>
      )}

      {queuedCases.length > 0 ? (
        <details className="lane-queued" open={primaryLane === "docs"}>
          <summary>
            Waiting to prepare <span className="muted">({queuedCases.length})</span>
          </summary>
          <ul className="lane-list compact">
            {queuedCases.map((item) => (
              <li key={item.case_id}>
                <Link className="lane-item" to={prepareHref(item)}>
                  <span className="lane-item-main">
                    <strong>{procedureDisplayName(item.procedure)}</strong>
                    <span className="muted">{item.patient_id}</span>
                  </span>
                  <span className="lane-cta">Prepare evidence pack</span>
                </Link>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );

  return (
    <section className="page today-page" data-testid="page-today">
      <header className="today-hero">
        <div className="today-hero-copy">
          <p className="eyebrow">
            {label} · {facilityLabel}
          </p>
          <h1 className="page-title" data-testid="heading-today">
            {copy.title}
          </h1>
          <p className="page-subtitle">{copy.subtitle}</p>
          <p className="live-stamp">
            <span aria-live="polite">{formatLiveAge(lastUpdatedAt, pushConnected)}</span>
            {" · "}
            <button type="button" className="text-link" onClick={refreshNow}>
              Refresh now
            </button>
            {" · "}
            <Link className="text-link" to="/visit">
              Visit note
            </Link>
            {" · "}
            <Link className="text-link" to="/visit#hospital-feed">
              Hospital feed
            </Link>
          </p>
        </div>
        {worklist ? (
          <dl className="today-pulse" aria-label="Today at a glance">
            {(primaryLane === "review" || canAdjudicate || isResident) && (
              <div>
                <dt>Review</dt>
                <dd>{clinicianCases.length}</dd>
              </div>
            )}
            <div>
              <dt>Notes needed</dt>
              <dd>{staffDocCases.length}</dd>
            </div>
            <div>
              <dt>SLA overdue</dt>
              <dd>
                {
                  (worklist.open_cases || []).filter((item) => item.sla_breached)
                    .length
                }
              </dd>
            </div>
          </dl>
        ) : null}
      </header>

      <form className="finder-bar today-finder" onSubmit={onJump}>
        <label className="search-field grow">
          <span className="sr-only">Quick patient lookup</span>
          <input
            type="search"
            value={jump}
            onChange={(e) => setJump(e.target.value)}
            placeholder="Jump to patient ID or name…"
            autoFocus
          />
        </label>
        <button className="btn btn-primary" type="submit">
          Open chart
        </button>
      </form>
      {jumpError ? (
        <p className="error" role="alert">
          {jumpError}
        </p>
      ) : null}

      {browserRecent.length > 0 ? (
        <div className="chip-row" aria-label="Recently opened in this browser">
          <span className="chip-label">Recent</span>
          {browserRecent.map((item) => (
            <Link key={item.patient_id} className="chip" to={`/patients/${item.patient_id}`}>
              {item.patient_id}
            </Link>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {!error && !worklist ? <p className="muted">Loading worklist…</p> : null}

      {worklist && (isSenior || isResident) && myCases.length > 0 ? (
        <section className="lane lane-primary" aria-label="My review queue">
          <header className="lane-head">
            <h2 className="lane-title">
              My review queue
              <span className="lane-count">{myCases.length}</span>
            </h2>
          </header>
          <ul className="lane-list">
            {myCases.slice(0, 8).map((item) => (
              <li key={`mine-${item.case_id}`}>
                <Link className="lane-item" to={clinicianHref(item)}>
                  <span className="lane-item-main">
                    <strong>{procedureDisplayName(item.procedure)}</strong>
                    <span className="muted">{item.patient_id}</span>
                  </span>
                  <span className="lane-cta">Open</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {worklist ? (
        <div
          className={`today-lanes today-lanes-${primaryLane === "docs" ? "staff" : "clinician"}`}
        >
          {primaryLane === "docs" ? (
            <>
              {docsLane}
              {reviewLane}
            </>
          ) : (
            <>
              {reviewLane}
              {docsLane}
            </>
          )}

          <section className="lane lane-charts" aria-labelledby="lane-charts-title">
            <header className="lane-head">
              <div>
                <h2 className="lane-title" id="lane-charts-title">
                  Recent charts
                </h2>
              </div>
              <div className="lane-head-actions">
                <Link className="text-link" to="/visit">
                  Add visit note
                </Link>
                <Link className="text-link" to="/patients">
                  Browse all
                </Link>
              </div>
            </header>

            {worklist.recent_patients.length === 0 ? (
              <p className="lane-empty">No patients on file yet.</p>
            ) : (
              <ul className="chart-strip">
                {worklist.recent_patients.slice(0, 8).map((item) => (
                  <li key={item.patient_id}>
                    <Link className="chart-tile" to={`/patients/${item.patient_id}`}>
                      <strong>{item.patient_id}</strong>
                      <span>{item.display_name}</span>
                      <span className="muted chart-tile-meta">
                        {item.condition_summary || "Open chart"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
