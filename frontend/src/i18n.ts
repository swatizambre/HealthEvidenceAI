/**
 * Shell, navigation and status-label dictionary (English / Hindi).
 * Page body copy stays English; everything a desk scans repeatedly is translated.
 */
import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "en" | "hi";

const en = {
  "shell.skip": "Skip to main content",
  "shell.brandSub": "Lifelong health record",
  "shell.facility": "Facility",
  "shell.signIn": "Demo sign-in",
  "shell.signedIn": "Signed in",
  "shell.help": "Help",
  "shell.language": "Language",
  "shell.loading": "Signing in…",
  "shell.footer":
    "Your lifelong health record with sources for every doctor. Not a medical device. Does not diagnose, prescribe, approve, or deny care.",
  "shell.footerInsurer": "Hospital cashless checklists are illustrative — confirm with each insurer/TPA.",

  "nav.label": "Application",
  "nav.queue": "Work queue",
  "nav.cases": "Cases",
  "nav.patients": "Patients",
  "nav.visit": "Visit note",
  "nav.reviews": "Reviews",
  "nav.myRecord": "My record",
  "nav.emergency": "Emergency card",
  "nav.share": "Share",
  "nav.family": "Family",
  "nav.addNote": "Add note",
  "nav.fullChart": "Full chart",
  "nav.reports": "Reports",

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

  "col.mrn": "MRN",
  "col.ageSex": "Age / sex",
  "col.activeCase": "Active case",
  "col.lastVisit": "Last visit",

  "common.search": "Search",
  "common.retry": "Try again",
  "common.unassigned": "Unassigned",
  "common.close": "Close",
  "common.refresh": "Refresh",
  "common.previous": "Previous",
  "common.next": "Next",
  "common.notRecorded": "Not recorded",

  "shell.settings": "Desk settings",
  "role.staff": "TPA / insurance desk",
  "role.resident": "Junior doctor (PG / MO)",
  "role.senior_clinician": "Consultant / senior MO",
  "role.admin": "Facility admin",
  "role.patient": "Patient (my record)",
  "facility.phc": "PHC / sub-centre OPD",
  "facility.chc": "CHC / block hospital",
  "facility.taluk": "Taluk / tehsil hospital",
  "facility.district": "District hospital",
  "facility.clinic": "Clinic / nursing home",
  "facility.multispecialty": "Urban multispecialty hospital",
  "facility.superspecialty": "Super-specialty / corporate centre",
  "facility.government": "Medical college / teaching hospital",

  "live.push": "Live push",
  "live.poll": "Live poll",
  "live.connecting": "connecting…",
  "live.justNow": "just now",
  "live.secondsAgo": "{n}s ago",
  "live.minutesAgo": "{n}m ago",

  "queue.subQueue": "Most urgent first: overdue, then least time left on the IRDAI clocks.",
  "queue.subCases": "Every cashless case at this facility, including closed ones.",
  "queue.searchLabel": "Search cases",
  "queue.searchPlaceholder": "Patient, MRN, case, insurer…",
  "queue.atGlance": "Desk at a glance",
  "queue.medianPrep": "Median prep time",
  "queue.minutes": "{n} min",
  "queue.open": "{n} open",
  "queue.filterStage": "Filter by stage",
  "queue.countOne": "{n} case",
  "queue.countOther": "{n} cases",
  "queue.loading": "Loading cases",
  "queue.empty": "No open cases",
  "queue.clearFilters": "Clear filters",
  "queue.openCase": "Open case {id} for {name}",

  "review.confirm": "Confirm",
  "review.sendBack": "Send back",
  "review.confirmedToast": "Checklist confirmed",
} as const;

export type MessageKey = keyof typeof en;

const hi: Record<MessageKey, string> = {
  "shell.skip": "मुख्य सामग्री पर जाएँ",
  "shell.brandSub": "आजीवन स्वास्थ्य रिकॉर्ड",
  "shell.facility": "अस्पताल",
  "shell.signIn": "डेमो साइन-इन",
  "shell.signedIn": "साइन इन",
  "shell.help": "सहायता",
  "shell.language": "भाषा",
  "shell.loading": "साइन इन हो रहा है…",
  "shell.footer":
    "आपका आजीवन स्वास्थ्य रिकॉर्ड — हर डॉक्टर के लिए स्रोतों के साथ। यह चिकित्सा उपकरण नहीं है। निदान, नुस्खा, स्वीकृति या अस्वीकृति नहीं करता।",
  "shell.footerInsurer": "अस्पताल कैशलेस चेकलिस्ट उदाहरण हैं — हर बीमा कंपनी/TPA से पुष्टि करें।",

  "nav.label": "एप्लिकेशन",
  "nav.queue": "कार्य सूची",
  "nav.cases": "केस",
  "nav.patients": "मरीज़",
  "nav.visit": "विज़िट नोट",
  "nav.reviews": "समीक्षा",
  "nav.myRecord": "मेरा रिकॉर्ड",
  "nav.emergency": "आपातकाल कार्ड",
  "nav.share": "साझा करें",
  "nav.family": "परिवार",
  "nav.addNote": "नोट जोड़ें",
  "nav.fullChart": "पूरा चार्ट",
  "nav.reports": "रिपोर्ट",

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

  "col.mrn": "MRN",
  "col.ageSex": "आयु / लिंग",
  "col.activeCase": "सक्रिय केस",
  "col.lastVisit": "पिछली विज़िट",

  "common.search": "खोजें",
  "common.retry": "फिर कोशिश करें",
  "common.unassigned": "किसी को नहीं सौंपा",
  "common.close": "बंद करें",
  "common.refresh": "रीफ़्रेश करें",
  "common.previous": "पिछला",
  "common.next": "अगला",
  "common.notRecorded": "दर्ज नहीं",

  "shell.settings": "डेस्क सेटिंग्स",
  "role.staff": "TPA / बीमा डेस्क",
  "role.resident": "जूनियर डॉक्टर (PG / MO)",
  "role.senior_clinician": "कंसल्टेंट / सीनियर MO",
  "role.admin": "अस्पताल एडमिन",
  "role.patient": "मरीज़ (मेरा रिकॉर्ड)",
  "facility.phc": "PHC / उप-केंद्र OPD",
  "facility.chc": "CHC / ब्लॉक अस्पताल",
  "facility.taluk": "तालुका / तहसील अस्पताल",
  "facility.district": "ज़िला अस्पताल",
  "facility.clinic": "क्लिनिक / नर्सिंग होम",
  "facility.multispecialty": "शहरी मल्टी-स्पेशलिटी अस्पताल",
  "facility.superspecialty": "सुपर-स्पेशलिटी / कॉर्पोरेट केंद्र",
  "facility.government": "मेडिकल कॉलेज / शिक्षण अस्पताल",

  "live.push": "लाइव अपडेट",
  "live.poll": "लाइव जाँच",
  "live.connecting": "जुड़ रहा है…",
  "live.justNow": "अभी",
  "live.secondsAgo": "{n} सेकंड पहले",
  "live.minutesAgo": "{n} मिनट पहले",

  "queue.subQueue": "सबसे ज़रूरी पहले: समय पार वाले, फिर IRDAI समय-सीमा में सबसे कम बचे समय वाले।",
  "queue.subCases": "इस अस्पताल के सभी कैशलेस केस, बंद केस सहित।",
  "queue.searchLabel": "केस खोजें",
  "queue.searchPlaceholder": "मरीज़, MRN, केस, बीमा कंपनी…",
  "queue.atGlance": "डेस्क एक नज़र में",
  "queue.medianPrep": "तैयारी का औसत (मध्य) समय",
  "queue.minutes": "{n} मिनट",
  "queue.open": "{n} खुले",
  "queue.filterStage": "चरण से छाँटें",
  "queue.countOne": "{n} केस",
  "queue.countOther": "{n} केस",
  "queue.loading": "केस लोड हो रहे हैं",
  "queue.empty": "कोई खुला केस नहीं",
  "queue.clearFilters": "फ़िल्टर हटाएँ",
  "queue.openCase": "{name} का केस {id} खोलें",

  "review.confirm": "पुष्टि करें",
  "review.sendBack": "वापस भेजें",
  "review.confirmedToast": "चेकलिस्ट की पुष्टि हुई",
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
