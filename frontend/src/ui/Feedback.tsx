import type { ReactNode } from "react";
import { Icon, type IconName } from "./icons";

/** An empty screen is an invitation to act: say what is missing and what to do. */
export function EmptyState({
  title,
  children,
  action,
  icon = "folder",
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: IconName;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name={icon} size={20} />
      </span>
      <div>
        <p className="empty-title">{title}</p>
        {children ? <div className="empty-body">{children}</div> : null}
        {action ? <div className="empty-action">{action}</div> : null}
      </div>
    </div>
  );
}

export function Skeleton({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div className="skeleton-block" role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, index) => (
        <span
          key={index}
          className="skeleton skeleton-line"
          style={{ width: `${92 - ((index * 17) % 40)}%` }}
        />
      ))}
    </div>
  );
}

export type NoticeTone = "info" | "warning" | "danger" | "success";

const NOTICE_ICON: Record<NoticeTone, IconName> = {
  info: "info",
  warning: "alert",
  danger: "alert",
  success: "check",
};

/** Inline message banner. Danger notices are announced as alerts. */
export function Notice({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: NoticeTone;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon name={NOTICE_ICON[tone]} />
      <div className="notice-body">
        {title ? <p className="notice-title">{title}</p> : null}
        {children ? <div>{children}</div> : null}
      </div>
      {action ? <div className="notice-action">{action}</div> : null}
    </div>
  );
}
