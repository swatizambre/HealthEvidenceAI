/** Small stroke icons (16px grid). Always decorative: pair with visible text. */
export type IconName =
  | "check"
  | "alert"
  | "x"
  | "clock"
  | "dot"
  | "send"
  | "question"
  | "arrow-right"
  | "queue"
  | "folder"
  | "users"
  | "note"
  | "shield"
  | "help"
  | "search"
  | "print"
  | "edit"
  | "chevron-down"
  | "doc"
  | "info";

const PATHS: Record<IconName, string> = {
  check: "M3.5 8.5l3 3 6-7",
  alert: "M8 2.5l6 11H2l6-11zM8 6.5v3.2M8 11.6v.1",
  x: "M4 4l8 8M12 4l-8 8",
  clock: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 5v3.2l2.2 1.4",
  dot: "M8 6.2a1.8 1.8 0 100 3.6 1.8 1.8 0 000-3.6z",
  send: "M2.5 8l11-5-4 11-2-4.5-5-1.5z",
  question: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM6.3 6.4a1.8 1.8 0 113 1.3c-.6.4-1.3.8-1.3 1.6M8 11.3v.1",
  "arrow-right": "M3 8h10M9 4l4 4-4 4",
  queue: "M2.5 4h11M2.5 8h11M2.5 12h7",
  folder: "M2 4.5h4l1.5 1.5H14v6.5H2v-8z",
  users: "M6 7.5a2.2 2.2 0 100-4.4 2.2 2.2 0 000 4.4zM1.8 13c.4-2.2 2.1-3.5 4.2-3.5s3.8 1.3 4.2 3.5M10.6 3.3a2.2 2.2 0 010 4.1M12 9.7c1.2.4 2 1.6 2.2 3.3",
  note: "M3.5 2.5h6l3 3v8h-9v-11zM9.5 2.5v3h3M5.5 8.5h5M5.5 11h3.5",
  shield: "M8 2l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V4l5-2zM5.8 8l1.6 1.6 2.9-3.2",
  help: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM6.3 6.4a1.8 1.8 0 113 1.3c-.6.4-1.3.8-1.3 1.6M8 11.3v.1",
  search: "M7 2.8a4.2 4.2 0 100 8.4 4.2 4.2 0 000-8.4zM10.2 10.2l3.3 3.3",
  print: "M4.5 6V2.5h7V6M4.5 11.5H2.5V6h11v5.5h-2M4.5 9.5h7v4h-7z",
  edit: "M10.5 2.8l2.7 2.7-7.5 7.5H3v-2.7l7.5-7.5z",
  "chevron-down": "M4 6l4 4 4-4",
  doc: "M4 2.5h5.5l2.5 2.5v8.5H4v-11zM6 7.5h4M6 10h4",
  info: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 7.2v3.6M8 5.2v.1",
};

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
