/**
 * Shell, navigation and status-label dictionary (English / Hindi).
 * Page body copy stays English; everything a desk scans repeatedly is translated.
 */
import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "en" | "hi";

const en = {
  "shell.skip": "Skip to main content",
  "shell.brandSub": "Cashless pre-auth desk",
  "shell.facility": "Facility",
  "shell.signIn": "Demo sign-in",
  "shell.signedIn": "Signed in",
  "shell.help": "Help",
  "shell.language": "Language",
  "shell.loading": "Signing in to the desk…",
  "shell.footer":
    "Prepares cashless pre-authorization paperwork and keeps a lifelong chart. Not a medical device. Does not diagnose, approve, or deny care.",
  "shell.footerInsurer": "Checklists and form fields are illustrative — confirm with each insurer/TPA.",

  "nav.label": "Application",
  "nav.queue": "Work queue",
  "nav.cases": "Cases",
  "nav.patients": "Patients",
  "nav.visit": "Visit note",
  "nav.reviews": "Reviews",
  "nav.myRecord": "My record",
  "nav.addNote": "Add note",
  "nav.fullChart": "Full chart",

  "stage.draft": "Draft",
  "stage.ready_to_send": "Ready to send",
  "stage.sent": "Sent to TPA",
  "stage.query": "TPA query",
  "stage.approved": "Approved",
  "stage.enhancement": "Enhancement",
  "stage.discharge_pending": "Discharge pending",
  "stage.discharge_sent": "Discharge sent",
  "stage.closed": "Closed",
  "stage.all": "All",

  "step.draft": "Draft",
  "step.ready": "Ready",
  "step.sent": "Sent",
  "step.query": "Query",
  "step.approved": "Approved",
  "step.discharge": "Discharge",
  "step.closed": "Closed",

  "item.SUPPORTED": "Found in chart",
  "item.SUPPORTED_ON_CASE": "On case",
  "item.MISSING": "Missing",
  "item.UNKNOWN": "Unclear",
  "item.NOT_SUPPORTED": "Doesn't match",

  "review.not_started": "Not reviewed",
  "review.awaiting_senior": "Awaiting senior",
  "review.acknowledged": "Senior confirmed",
  "review.needs_documentation": "Sent back",

  "severity.blocker": "Blocker",
  "severity.warning": "Warning",
  "severity.info": "Note",

  "clock.overdue": "Overdue {t}",
  "clock.left": "{t} left",
  "clock.none": "No clock",
  "clock.due": "Due {at}",

  "stats.overdue": "Overdue",
  "stats.due60": "Due < 60 min",
  "stats.queries": "Open queries",
  "stats.ready": "Ready to send",
  "stats.senior": "Awaiting senior",

  "col.patient": "Patient",
  "col.treatment": "Treatment",
  "col.payer": "Insurer / TPA",
  "col.estimate": "Est. ₹",
  "col.stage": "Stage",
  "col.readiness": "Readiness",
  "col.clock": "Clock",
  "col.assignee": "Assignee",

  "common.search": "Search",
  "common.retry": "Try again",
  "common.unassigned": "Unassigned",
  "common.close": "Close",
} as const;

export type MessageKey = keyof typeof en;

const hi: Record<MessageKey, string> = {
  "shell.skip": "मुख्य सामग्री पर जाएँ",
  "shell.brandSub": "कैशलेस प्री-ऑथ डेस्क",
  "shell.facility": "अस्पताल",
  "shell.signIn": "डेमो साइन-इन",
  "shell.signedIn": "साइन इन",
  "shell.help": "सहायता",
  "shell.language": "भाषा",
  "shell.loading": "डेस्क में साइन इन हो रहा है…",
  "shell.footer":
    "कैशलेस प्री-ऑथराइज़ेशन के कागज़ात तैयार करता है और आजीवन चार्ट रखता है। यह चिकित्सा उपकरण नहीं है। निदान, स्वीकृति या अस्वीकृति नहीं करता।",
  "shell.footerInsurer": "चेकलिस्ट और फ़ॉर्म फ़ील्ड उदाहरण हैं — हर बीमा कंपनी/TPA से पुष्टि करें।",

  "nav.label": "एप्लिकेशन",
  "nav.queue": "कार्य सूची",
  "nav.cases": "केस",
  "nav.patients": "मरीज़",
  "nav.visit": "विज़िट नोट",
  "nav.reviews": "समीक्षा",
  "nav.myRecord": "मेरा रिकॉर्ड",
  "nav.addNote": "नोट जोड़ें",
  "nav.fullChart": "पूरा चार्ट",

  "stage.draft": "ड्राफ़्ट",
  "stage.ready_to_send": "भेजने को तैयार",
  "stage.sent": "TPA को भेजा",
  "stage.query": "TPA प्रश्न",
  "stage.approved": "स्वीकृत",
  "stage.enhancement": "राशि वृद्धि",
  "stage.discharge_pending": "डिस्चार्ज लंबित",
  "stage.discharge_sent": "डिस्चार्ज भेजा",
  "stage.closed": "बंद",
  "stage.all": "सभी",

  "step.draft": "ड्राफ़्ट",
  "step.ready": "तैयार",
  "step.sent": "भेजा",
  "step.query": "प्रश्न",
  "step.approved": "स्वीकृत",
  "step.discharge": "डिस्चार्ज",
  "step.closed": "बंद",

  "item.SUPPORTED": "चार्ट में मिला",
  "item.SUPPORTED_ON_CASE": "केस में दर्ज",
  "item.MISSING": "नहीं मिला",
  "item.UNKNOWN": "अस्पष्ट",
  "item.NOT_SUPPORTED": "मेल नहीं खाता",

  "review.not_started": "समीक्षा नहीं हुई",
  "review.awaiting_senior": "सीनियर की प्रतीक्षा",
  "review.acknowledged": "सीनियर ने पुष्टि की",
  "review.needs_documentation": "वापस भेजा",

  "severity.blocker": "रुकावट",
  "severity.warning": "चेतावनी",
  "severity.info": "नोट",

  "clock.overdue": "{t} देर",
  "clock.left": "{t} बाकी",
  "clock.none": "कोई समय-सीमा नहीं",
  "clock.due": "नियत {at}",

  "stats.overdue": "समय पार",
  "stats.due60": "60 मिनट में देय",
  "stats.queries": "खुले प्रश्न",
  "stats.ready": "भेजने को तैयार",
  "stats.senior": "सीनियर की प्रतीक्षा",

  "col.patient": "मरीज़",
  "col.treatment": "उपचार",
  "col.payer": "बीमा / TPA",
  "col.estimate": "अनुमान ₹",
  "col.stage": "चरण",
  "col.readiness": "तैयारी",
  "col.clock": "समय",
  "col.assignee": "ज़िम्मेदार",

  "common.search": "खोजें",
  "common.retry": "फिर कोशिश करें",
  "common.unassigned": "किसी को नहीं सौंपा",
  "common.close": "बंद करें",
};

const DICTIONARIES: Record<Lang, Record<MessageKey, string>> = { en, hi };
const LANG_KEY = "he.ai.lang";

export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

type I18nValue = { lang: Lang; setLang: (next: Lang) => void; t: Translate };

const I18nContext = createContext<I18nValue | null>(null);

function readStoredLang(): Lang {
  try {
    const raw = localStorage.getItem(LANG_KEY);
    if (raw === "hi" || raw === "en") {
      return raw;
    }
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => readStoredLang());

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(LANG_KEY, next);
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback<Translate>(
    (key, vars) => {
      let text = DICTIONARIES[lang][key] ?? en[key];
      if (vars) {
        for (const [name, value] of Object.entries(vars)) {
          text = text.split(`{${name}}`).join(String(value));
        }
      }
      return text;
    },
    [lang],
  );

  const value = useMemo<I18nValue>(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return createElement(I18nContext.Provider, { value }, children);
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}
