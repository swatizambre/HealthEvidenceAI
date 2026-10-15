/**
 * One status vocabulary for the whole desk. Every pill pairs color with an icon and text,
 * so status never depends on color alone.
 */
import type { ChecklistStatus, FindingSeverity, ReviewState, Stage } from "../deskApi";
import { isStage } from "../deskApi";
import { useI18n, type MessageKey } from "../i18n";
import { Icon, type IconName } from "./icons";

export type Tone = "neutral" | "info" | "progress" | "warning" | "danger" | "success";

const TONE_ICON: Record<Tone, IconName> = {
  neutral: "dot",
  info: "dot",
  progress: "send",
  warning: "alert",
  danger: "alert",
  success: "check",
};

export function StatusPill({
  tone,
  label,
  icon,
  title,
}: {
  tone: Tone;
  label: string;
  icon?: IconName;
  title?: string;
}) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      <Icon name={icon ?? TONE_ICON[tone]} size={12} />
      <span>{label}</span>
    </span>
  );
}

export const STAGE_TONE: Record<Stage, Tone> = {
  draft: "neutral",
  ready_to_send: "info",
  sent: "progress",
  query: "warning",
  approved: "success",
  enhancement: "warning",
  discharge_pending: "info",
  discharge_sent: "progress",
  closed: "neutral",
};

const STAGE_ICON: Record<Stage, IconName> = {
  draft: "edit",
  ready_to_send: "check",
  sent: "send",
  query: "question",
  approved: "check",
  enhancement: "alert",
  discharge_pending: "doc",
  discharge_sent: "send",
  closed: "dot",
};

export function stageKey(stage: Stage): MessageKey {
  return `stage.${stage}` as MessageKey;
}

export function StagePill({ stage, fallbackLabel }: { stage: string; fallbackLabel?: string }) {
  const { t } = useI18n();
  if (!isStage(stage)) {
    return <StatusPill tone="neutral" label={fallbackLabel || stage || "—"} />;
  }
  return <StatusPill tone={STAGE_TONE[stage]} icon={STAGE_ICON[stage]} label={t(stageKey(stage))} />;
}

export const ITEM_TONE: Record<ChecklistStatus, Tone> = {
  SUPPORTED: "success",
  MISSING: "danger",
  UNKNOWN: "warning",
  NOT_SUPPORTED: "danger",
};

const ITEM_ICON: Record<ChecklistStatus, IconName> = {
  SUPPORTED: "check",
  MISSING: "x",
  UNKNOWN: "question",
  NOT_SUPPORTED: "alert",
};

export function ItemStatusPill({
  status,
  onCase = false,
}: {
  status: ChecklistStatus;
  /** Form fields are satisfied by case details, not chart excerpts. */
  onCase?: boolean;
}) {
  const { t } = useI18n();
  const label =
    onCase && status === "SUPPORTED" ? t("item.SUPPORTED_ON_CASE") : t(`item.${status}` as MessageKey);
  return <StatusPill tone={ITEM_TONE[status]} icon={ITEM_ICON[status]} label={label} />;
}

const REVIEW_TONE: Record<ReviewState, Tone> = {
  not_started: "neutral",
  awaiting_senior: "info",
  acknowledged: "success",
  needs_documentation: "warning",
};

export function ReviewPill({ state }: { state: ReviewState }) {
  const { t } = useI18n();
  return <StatusPill tone={REVIEW_TONE[state]} label={t(`review.${state}` as MessageKey)} />;
}

const SEVERITY_TONE: Record<FindingSeverity, Tone> = {
  blocker: "danger",
  warning: "warning",
  info: "info",
};

export function SeverityPill({ severity }: { severity: FindingSeverity }) {
  const { t } = useI18n();
  return (
    <StatusPill
      tone={SEVERITY_TONE[severity]}
      icon={severity === "info" ? "info" : "alert"}
      label={t(`severity.${severity}` as MessageKey)}
    />
  );
}
