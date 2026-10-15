/** Shared formatters: ₹ with Indian grouping, local date/time, durations, ages. */
import { useEffect, useState } from "react";

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const INR_PLAIN = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** ₹1,25,000 */
export function formatInr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return INR.format(value);
}

/** 1,25,000 (no symbol; for columns already labelled ₹). */
export function formatInrPlain(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return INR_PLAIN.format(value);
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Date-only values (DOB, expected delivery) are calendar days, not UTC midnights.
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 14 Oct, 14:35 (browser time zone; IST on site). */
export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** 15 Oct 2026, 08:54 (with the year, for printed forms). */
export function formatDateTimeLong(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const day = date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const time = date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day}, ${time}`;
}

/** "male" → "Male", "self_pay" → "Self pay". */
export function humanize(value: string | null | undefined): string {
  const text = (value || "").trim().replace(/_/g, " ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

/** 14 Oct 2026 */
export function formatDate(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** 45m · 2h 05m · 3d 4h */
export function formatDuration(totalMinutes: number): string {
  const minutes = Math.max(0, Math.round(Math.abs(totalMinutes)));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return `${hours}h ${String(rest).padStart(2, "0")}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

export function ageFromDob(dob: string | null | undefined): number | null {
  const born = parseDate(dob);
  if (!born) return null;
  const today = new Date();
  let age = today.getFullYear() - born.getFullYear();
  const monthDelta = today.getMonth() - born.getMonth();
  if (monthDelta < 0 || (monthDelta === 0 && today.getDate() < born.getDate())) {
    age -= 1;
  }
  return age >= 0 ? age : null;
}

/** "62 · M" style age/sex label. */
export function ageSex(age: number | null | undefined, sex: string | null | undefined): string {
  const s = (sex || "").trim().toLowerCase();
  const letter = s.startsWith("m") ? "M" : s.startsWith("f") ? "F" : s ? "O" : "";
  const parts = [age != null ? `${age}y` : "", letter].filter(Boolean);
  return parts.length ? parts.join(" / ") : "—";
}

/** Re-render every `intervalMs` so clocks count down without refetching. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
