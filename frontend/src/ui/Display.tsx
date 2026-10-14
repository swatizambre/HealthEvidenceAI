import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { formatInr } from "./format";
import { Icon } from "./icons";

/** ₹ amount with Indian digit grouping (₹1,25,000). */
export function Money({ value, className }: { value: number | null | undefined; className?: string }) {
  return <span className={`money${className ? ` ${className}` : ""}`}>{formatInr(value)}</span>;
}

/**
 * The one readiness number: supported / required over the case checklist.
 * Text always states the number; the bar is supplementary.
 */
export function ReadinessMeter({
  percent,
  label,
  size = "sm",
}: {
  percent: number;
  label?: string;
  size?: "sm" | "lg";
}) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  const tone = value >= 100 ? "success" : value >= 70 ? "info" : "warning";
  return (
    <div className={`meter meter-${size} meter-${tone}`}>
      <div className="meter-head">
        <strong className="meter-value">{value}%</strong>
        {label ? <span className="meter-label">{label}</span> : null}
      </div>
      <div
        className="meter-track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-label={`Readiness ${value}%`}
      >
        <span className="meter-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export type TabItem<K extends string> = { id: K; label: string; count?: number };

/** Accessible tablist with roving focus (ArrowLeft/ArrowRight/Home/End). */
export function Tabs<K extends string>({
  items,
  active,
  onChange,
  label,
  idPrefix,
}: {
  items: TabItem<K>[];
  active: K;
  onChange: (id: K) => void;
  label: string;
  idPrefix: string;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((item) => item.id === active);
    let next = -1;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = items.length - 1;
    if (next < 0) return;
    event.preventDefault();
    onChange(items[next].id);
    const button = listRef.current?.querySelector<HTMLButtonElement>(`#${idPrefix}-tab-${items[next].id}`);
    button?.focus();
  }

  return (
    <div className="tabs" role="tablist" aria-label={label} ref={listRef} onKeyDown={onKeyDown}>
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            id={`${idPrefix}-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel`}
            tabIndex={selected ? 0 : -1}
            className={`tab${selected ? " is-active" : ""}`}
            onClick={() => onChange(item.id)}
          >
            <span>{item.label}</span>
            {item.count != null ? <span className="tab-count">{item.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Side panel dialog. Escape closes; focus moves in on open and back to the opener on close.
 */
export function Drawer({
  open,
  title,
  onClose,
  children,
  footer,
  width = "md",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: "md" | "lg";
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<Element | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(
      "input, select, textarea, button:not(.drawer-close), [href], [tabindex]:not([tabindex='-1'])",
    );
    (first ?? panel)?.focus();

    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      );
      if (focusable.length === 0) return;
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const opener = openerRef.current;
      if (opener instanceof HTMLElement) {
        opener.focus();
      }
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="drawer-root">
      <div className="drawer-scrim" onClick={onClose} aria-hidden="true" />
      <div
        className={`drawer drawer-${width}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
        tabIndex={-1}
      >
        <header className="drawer-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn drawer-close" onClick={onClose}>
            <Icon name="x" />
            <span className="sr-only">Close</span>
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer ? <footer className="drawer-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}
