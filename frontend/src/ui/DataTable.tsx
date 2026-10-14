import type { KeyboardEvent, MouseEvent, ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "start" | "end";
  /** Narrow columns keep their content on one line. */
  nowrap?: boolean;
  className?: string;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  caption: ReactNode;
  /** Visually hide the caption (still announced). */
  captionHidden?: boolean;
  onRowActivate?: (row: T) => void;
  rowLabel?: (row: T) => string;
  rowClassName?: (row: T) => string;
  loading?: boolean;
  skeletonRows?: number;
  empty?: ReactNode;
  className?: string;
};

function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("a, button, input, select, textarea, label"));
}

/**
 * Dense, scannable table: sticky header, row hover, and keyboard row activation
 * (Enter/Space opens; ArrowUp/ArrowDown move between rows).
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  captionHidden = false,
  onRowActivate,
  rowLabel,
  rowClassName,
  loading = false,
  skeletonRows = 6,
  empty,
  className,
}: Props<T>) {
  const activatable = Boolean(onRowActivate);

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: T) {
    if (event.target !== event.currentTarget) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onRowActivate?.(row);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const sibling =
        event.key === "ArrowDown"
          ? event.currentTarget.nextElementSibling
          : event.currentTarget.previousElementSibling;
      if (sibling instanceof HTMLElement) {
        sibling.focus();
      }
    }
  }

  function onRowClick(event: MouseEvent<HTMLTableRowElement>, row: T) {
    if (isInteractive(event.target)) {
      return;
    }
    onRowActivate?.(row);
  }

  const showEmpty = !loading && rows.length === 0;

  return (
    <div className={`table-scroll${className ? ` ${className}` : ""}`}>
      <table className={`data-table${activatable ? " is-activatable" : ""}`}>
        <caption className={captionHidden ? "sr-only" : undefined}>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={[column.align === "end" ? "align-end" : "", column.className || ""]
                  .filter(Boolean)
                  .join(" ") || undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody aria-busy={loading || undefined}>
          {loading
            ? Array.from({ length: skeletonRows }, (_, index) => (
                <tr key={`skeleton-${index}`} className="skeleton-row" aria-hidden="true">
                  {columns.map((column) => (
                    <td key={column.key}>
                      <span className="skeleton skeleton-line" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  className={rowClassName?.(row) || undefined}
                  tabIndex={activatable ? 0 : undefined}
                  aria-label={activatable && rowLabel ? rowLabel(row) : undefined}
                  onClick={activatable ? (event) => onRowClick(event, row) : undefined}
                  onKeyDown={activatable ? (event) => onRowKeyDown(event, row) : undefined}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={[
                        column.align === "end" ? "align-end" : "",
                        column.nowrap ? "nowrap" : "",
                        column.className || "",
                      ]
                        .filter(Boolean)
                        .join(" ") || undefined}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
          {showEmpty ? (
            <tr className="empty-row">
              <td colSpan={columns.length}>{empty ?? "Nothing to show."}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
