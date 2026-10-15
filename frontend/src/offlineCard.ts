import type { EmergencyCard } from "./api";

/**
 * The patient's own emergency card, kept on their phone only when they switch it on,
 * so it opens with no signal (the service worker keeps the app itself available).
 * Browser storage can be blocked or cleared, so every access is guarded.
 */
const KEY = "he.emergencyCard.v1";

export interface SavedCard {
  savedAt: string;
  card: EmergencyCard;
}

export function loadSavedCard(): SavedCard | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SavedCard;
    return parsed && parsed.card && parsed.savedAt ? parsed : null;
  } catch {
    return null;
  }
}

export function saveCard(card: EmergencyCard): SavedCard | null {
  const entry: SavedCard = { savedAt: new Date().toISOString(), card };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entry));
    return entry;
  } catch {
    return null;
  }
}

export function forgetSavedCard(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: nothing saved */
  }
}
