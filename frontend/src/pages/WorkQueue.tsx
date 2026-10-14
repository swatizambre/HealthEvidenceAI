import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  STAGES,
  deskErrorMessage,
  getDeskStats,
  getDeskWorklist,
  isEndpointMissing,
  isStage,
  PAYER_LABEL,
  type DeskStats,
  type DeskWorklist,
  type Stage,
  type WorklistItem,
} from "../deskApi";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { useI18n } from "../i18n";
import {
  Button,
  ClockChip,
  DataTable,
  EmptyState,
  Icon,
  Notice,
  StagePill,
  Tabs,
  ageSex,
  clockState,
  formatInrPlain,
  useNow,
  type Column,
  type TabItem,
} from "../ui";
import { stageKey } from "../ui/StatusPill";

const PAGE_SIZE = 50;

function payerPrimary(item: Pick<WorklistItem, "payer_type" | "insurer_name" | "tpa_name">): string {
  if (item.insurer_name) return item.insurer_name;
  return PAYER_LABEL[item.payer_type] ?? "—";
}

function payerSecondary(item: Pick<WorklistItem, "payer_type" | "insurer_name" | "tpa_name" | "policy_last4">): string {
  const parts: string[] = [];
  if (item.tpa_name) parts.push(`via ${item.tpa_name}`);
  else if (item.insurer_name && item.payer_type !== "insurer") parts.push(PAYER_LABEL[item.payer_type] ?? "");
  if (item.policy_last4) parts.push(`Policy\u00a0••${item.policy_last4}`);
  return parts.filter(Boolean).join(", ");
}

function StatTile({
  value,
  label,
  tone,
  onClick,
  to,
}: {
  value: number | null;
  label: string;
  tone: "danger" | "warning" | "neutral";
  onClick?: () => void;
  to?: string;
}) {
  const active = value != null && value > 0;
  const className = `stat stat-${active ? tone : "neutral"}${onClick || to ? " stat-action" : ""}`;
  const body = (
    <>
      <span className="stat-value">{value == null ? "–" : value}</span>
      <span className="stat-label">
        {active && tone !== "neutral" ? <Icon name={tone === "danger" ? "alert" : "clock"} size={14} /> : null}
        {label}
      </span>
    </>
  );
  if (to) {
    return (
      <li>
        <Link className={className} to={to}>
          {body}
        </Link>
      </li>
    );
  }
  if (onClick) {
    return (
      <li>
        <button type="button" className={className} onClick={onClick}>
          {body}
        </button>
      </li>
    );
  }
  return (
    <li>
      <div className={className}>{body}</div>
    </li>
  );
}

type Mode = "queue" | "cases";

export function WorkQueuePage({ mode }: { mode: Mode }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const now = useNow(30_000);
  const [searchParams, setSearchParams] = useSearchParams();
  const stageParam = searchParams.get("stage") || "";
  const stage: Stage | "" = isStage(stageParam) ? stageParam : "";
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debounced, setDebounced] = useState(query.trim());
  const [offset, setOffset] = useState(0);
  const [worklist, setWorklist] = useState<DeskWorklist | null>(null);
  const [stats, setStats] = useState<DeskStats | null>(null);
  const [error, setError] = useState<{ message: string; missing: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setOffset(0);
  }, [debounced, stage]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) {
        return;
      }
      event.preventDefault();
      searchRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const [list, nextStats] = await Promise.all([
        getDeskWorklist({ stage, q: debounced, limit: PAGE_SIZE, offset }),
        mode === "queue" ? getDeskStats().catch(() => null) : Promise.resolve(null),
      ]);
      if (seq !== requestSeq.current) return;
      setWorklist(list);
      setStats(nextStats);
      setError(null);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError({
        message: deskErrorMessage(err, "Could not load the work queue."),
        missing: isEndpointMissing(err),
      });
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [stage, debounced, offset, mode]);

  useEffect(() => {
    setLoading(true);
  }, [stage, debounced, offset]);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(load, { intervalMs: 60_000 });

  // useLiveRefresh keeps the latest loader in a ref; refetch when filters change.
  useEffect(() => {
    void load();
  }, [load]);

  function setStage(next: Stage | "") {
    const params = new URLSearchParams(searchParams);
    if (next) params.set("stage", next);
    else params.delete("stage");
    setSearchParams(params, { replace: true });
  }

  const counts = worklist?.counts ?? {};
  const allCount = STAGES.reduce((sum, key) => sum + (counts[key] ?? 0), 0);

  const tabItems: TabItem<Stage | "all">[] = [
    { id: "all", label: t("stage.all"), count: worklist ? allCount : undefined },
    // Stages with no cases are hidden (unless selected) so the filter row stays scannable.
    ...STAGES.filter((key) => !worklist || key === stage || (counts[key] ?? 0) > 0).map((key) => ({
      id: key,
      label: t(stageKey(key)),
      count: worklist ? counts[key] ?? 0 : undefined,
    })),
  ];

  const columns: Column<WorklistItem>[] = [
    {
      key: "patient",
      header: t("col.patient"),
      render: (row) => (
        <div className="cell-stack">
          <Link className="cell-primary row-link" to={`/cases/${encodeURIComponent(row.case_id)}`}>
            {row.patient_name || row.patient_id}
          </Link>
          <span className="cell-secondary">
            <span className="nowrap">{row.mrn ? `MRN ${row.mrn}` : row.patient_id}</span>
            <span className="sep" aria-hidden="true" />
            <span className="nowrap">{ageSex(row.age, row.sex)}</span>
          </span>
        </div>
      ),
    },
    {
      key: "treatment",
      header: t("col.treatment"),
      render: (row) => (
        <div className="cell-stack">
          <span className="cell-primary-text">{row.proposed_treatment || "Not recorded"}</span>
          <span className="cell-secondary">{row.case_id}</span>
        </div>
      ),
    },
    {
      key: "payer",
      header: t("col.payer"),
      render: (row) => (
        <div className="cell-stack">
          <span className="cell-primary-text">{payerPrimary(row)}</span>
          <span className="cell-secondary">{payerSecondary(row)}</span>
        </div>
      ),
    },
    {
      key: "estimate",
      header: t("col.estimate"),
      align: "end",
      nowrap: true,
      render: (row) => <span className="num">{formatInrPlain(row.estimated_cost_inr)}</span>,
    },
    {
      key: "stage",
      header: t("col.stage"),
      nowrap: true,
      render: (row) => <StagePill stage={row.stage} fallbackLabel={row.stage_label} />,
    },
    {
      key: "readiness",
      header: t("col.readiness"),
      nowrap: true,
      render: (row) => (
        <div className="mini-meter" title={`${row.readiness_percent}% of required items supported`}>
          <span className="num">{Math.round(row.readiness_percent)}%</span>
          <span className="mini-meter-track" aria-hidden="true">
            <span
              className={`mini-meter-fill${row.readiness_percent >= 100 ? " is-full" : ""}`}
              style={{ width: `${Math.max(0, Math.min(100, row.readiness_percent))}%` }}
            />
          </span>
          {row.open_items > 0 ? (
            <span className="cell-secondary">{row.open_items} open</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "clock",
      header: t("col.clock"),
      nowrap: true,
      render: (row) => <ClockChip clock={row.clock} />,
    },
    {
      key: "assignee",
      header: t("col.assignee"),
      render: (row) =>
        row.assigned_to ? (
          <span className="cell-primary-text">{row.assigned_to.replace(/^desk:/, "")}</span>
        ) : (
          <span className="muted">{t("common.unassigned")}</span>
        ),
    },
  ];

  const title = mode === "queue" ? t("nav.queue") : t("nav.cases");
  const items = worklist?.items ?? [];
  const total = worklist?.total ?? 0;

  return (
    <section className="page page-wide">
      <header className="page-head">
        <div>
          {mode === "queue" ? (
            <h1 className="page-title" data-testid="heading-today">
              {title}
            </h1>
          ) : (
            <h1 className="page-title">{title}</h1>
          )}
          <p className="page-sub">
            {mode === "queue"
              ? "Most urgent first: overdue, then least time left on the IRDAI clocks."
              : "Every cashless case at this facility, including closed ones."}
            <span className="live-stamp">
              {formatLiveAge(lastUpdatedAt, pushConnected)}
              <button type="button" className="text-link" onClick={refreshNow}>
                Refresh
              </button>
            </span>
          </p>
        </div>
        <div className="page-actions">
          <label className="search">
            <Icon name="search" />
            <span className="sr-only">Search cases</span>
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Patient, MRN, case, insurer…"
              autoComplete="off"
            />
            <kbd aria-hidden="true">/</kbd>
          </label>
        </div>
      </header>

      {mode === "queue" && !error?.missing ? (
        <ul className="stat-strip" aria-label="Desk at a glance">
          <StatTile value={stats?.overdue ?? null} label={t("stats.overdue")} tone="danger" />
          <StatTile value={stats?.due_within_60m ?? null} label={t("stats.due60")} tone="warning" />
          <StatTile
            value={stats?.queries_open ?? null}
            label={t("stats.queries")}
            tone="warning"
            onClick={() => setStage("query")}
          />
          <StatTile
            value={stats?.ready_to_send ?? null}
            label={t("stats.ready")}
            tone="neutral"
            onClick={() => setStage("ready_to_send")}
          />
          <StatTile
            value={stats?.awaiting_senior ?? null}
            label={t("stats.senior")}
            tone="neutral"
            to="/reviews"
          />
          {stats?.median_prep_minutes != null ? (
            <li className="stat-note">
              Median prep time <strong>{stats.median_prep_minutes} min</strong>
            </li>
          ) : null}
        </ul>
      ) : null}

      <div className="toolbar">
        <Tabs
          items={tabItems}
          active={stage || "all"}
          onChange={(id) => setStage(id === "all" ? "" : id)}
          label="Filter by stage"
          idPrefix="stage"
        />
      </div>

      <div id="stage-panel" role="tabpanel" aria-labelledby={`stage-tab-${stage || "all"}`}>
        {error ? (
          <Notice
            tone={error.missing ? "warning" : "danger"}
            title={error.missing ? "Work queue not available yet" : "Could not load the work queue"}
            action={
              <Button size="sm" onClick={refreshNow}>
                {t("common.retry")}
              </Button>
            }
          >
            {error.message}
            {error.missing ? (
              <>
                {" "}
                You can still open <Link to="/patients">Patients</Link> or{" "}
                <Link to="/reviews">Reviews</Link>.
              </>
            ) : null}
          </Notice>
        ) : (
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(row) => row.case_id}
            caption={
              loading && !worklist
                ? "Loading cases"
                : `${total} case${total === 1 ? "" : "s"}${stage ? ` in ${t(stageKey(stage))}` : ""}${debounced ? ` matching “${debounced}”` : ""}`
            }
            loading={loading && !worklist}
            onRowActivate={(row) => navigate(`/cases/${encodeURIComponent(row.case_id)}`)}
            rowLabel={(row) => `Open case ${row.case_id} for ${row.patient_name}`}
            rowClassName={(row) => {
              const state = clockState(row.clock, now);
              return state.overdue ? "row-overdue" : state.tone === "warning" ? "row-due-soon" : "";
            }}
            empty={
              <EmptyState
                icon="queue"
                title={debounced ? `No cases match “${debounced}”` : stage ? `No cases in ${t(stageKey(stage))}` : "No open cases"}
                action={
                  debounced || stage ? (
                    <Button
                      size="sm"
                      onClick={() => {
                        setQuery("");
                        setStage("");
                      }}
                    >
                      Clear filters
                    </Button>
                  ) : undefined
                }
              >
                {debounced || stage
                  ? "Try another search or stage."
                  : "New admissions and planned procedures appear here once a case is opened from the patient chart."}
              </EmptyState>
            }
          />
        )}

        {worklist && total > PAGE_SIZE ? (
          <div className="pager">
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </Button>
            <span className="muted">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <Button size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Next
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
