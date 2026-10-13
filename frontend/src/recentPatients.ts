const KEY = "heai.recentPatients";
const MAX = 6;

export type RecentPatient = {
  patient_id: string;
  display_name: string;
};

export function readRecentPatients(): RecentPatient[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RecentPatient[];
    return Array.isArray(parsed) ? parsed.slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function pushRecentPatient(item: RecentPatient): void {
  const next = [
    item,
    ...readRecentPatients().filter((entry) => entry.patient_id !== item.patient_id),
  ].slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(next));
}
