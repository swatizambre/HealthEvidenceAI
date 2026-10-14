import type { ClockKind, DeskClock } from "../deskApi";
import { useI18n } from "../i18n";
import { formatDateTime, formatDuration, parseDate, useNow } from "./format";
import { Icon } from "./icons";

/** Length of each regulatory/desk window, used to draw how much of it is left. */
const WINDOW_MINUTES: Record<ClockKind, number> = {
  insurer_decision: 60, // IRDAI: 1 hour for cashless pre-auth decision
  final_approval: 180, // IRDAI: 3 hours for final discharge approval
  query_response: 24 * 60, // desk default for answering a TPA query
  prep: 60,
  none: 60,
};

export type ClockState = {
  minutesLeft: number | null;
  overdue: boolean;
  tone: "danger" | "warning" | "neutral" | "none";
  fraction: number;
};

export function clockState(clock: DeskClock | null | undefined, now: number): ClockState {
  if (!clock || clock.kind === "none") {
    return { minutesLeft: null, overdue: false, tone: "none", fraction: 0 };
  }
  const due = parseDate(clock.due_at);
  const minutesLeft = due ? (due.getTime() - now) / 60_000 : clock.minutes_left;
  if (minutesLeft == null) {
    return { minutesLeft: null, overdue: false, tone: "none", fraction: 0 };
  }
  const overdue = clock.overdue || minutesLeft < 0;
  const tone = overdue ? "danger" : minutesLeft < 60 ? "warning" : "neutral";
  const fraction = overdue ? 0 : Math.min(1, Math.max(0, minutesLeft / WINDOW_MINUTES[clock.kind]));
  return { minutesLeft, overdue, tone, fraction };
}

function Ring({ fraction, size }: { fraction: number; size: number }) {
  const radius = size / 2 - 2;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg className="clock-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={radius} className="clock-ring-track" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        className="clock-ring-fill"
        strokeDasharray={`${circumference * fraction} ${circumference}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
  );
}

/**
 * Due/overdue chip: overdue = danger, under 60 min = warning, otherwise neutral.
 * The absolute due time is always visible as secondary text (and on hover).
 */
export function ClockChip({
  clock,
  size = "sm",
  showLabel = false,
}: {
  clock: DeskClock | null | undefined;
  size?: "sm" | "lg";
  showLabel?: boolean;
}) {
  const { t } = useI18n();
  const now = useNow(30_000);
  const state = clockState(clock, now);

  if (!clock || state.tone === "none" || state.minutesLeft == null) {
    return <span className="clock clock-none">{t("clock.none")}</span>;
  }

  const duration = formatDuration(state.minutesLeft);
  const main = state.overdue ? t("clock.overdue", { t: duration }) : t("clock.left", { t: duration });
  const dueText = clock.due_at ? t("clock.due", { at: formatDateTime(clock.due_at) }) : "";

  return (
    <span className={`clock clock-${state.tone} clock-${size}`} title={[clock.label, dueText].filter(Boolean).join(" · ")}>
      {state.overdue ? <Icon name="alert" size={size === "lg" ? 18 : 14} /> : <Ring fraction={state.fraction} size={size === "lg" ? 22 : 14} />}
      <span className="clock-text">
        <strong>{main}</strong>
        {showLabel && clock.label ? <span className="clock-label">{clock.label}</span> : null}
        {dueText ? <span className="clock-due">{dueText}</span> : null}
      </span>
    </span>
  );
}
