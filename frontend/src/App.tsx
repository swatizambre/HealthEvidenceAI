import { useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { deploymentBannerText } from "./api";
import { HelpChat } from "./components/HelpChat";
import { useI18n, type Lang, type MessageKey } from "./i18n";
import { facilityOptions, useRole, type DeskRole, type FacilityType } from "./roleContext";
import { CaseWorkspacePage } from "./pages/CaseWorkspace";
import { MyRecordPage } from "./pages/MyRecord";
import { OpdIngestPage } from "./pages/OpdIngest";
import { PatientDetailPage } from "./pages/PatientDetail";
import { PatientsPage } from "./pages/Patients";
import { ReviewsPage } from "./pages/Reviews";
import { WorkQueuePage } from "./pages/WorkQueue";
import { Icon, type IconName } from "./ui";

type NavItem = { to: string; key: MessageKey; icon: IconName; end?: boolean };

const ROLE_IDS: DeskRole[] = ["staff", "resident", "senior_clinician", "admin", "patient"];

const LANGS: { id: Lang; label: string; name: string }[] = [
  { id: "en", label: "EN", name: "English" },
  { id: "hi", label: "हिंदी", name: "Hindi" },
];

export function App() {
  const { t, lang, setLang } = useI18n();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const headerRef = useRef<HTMLElement | null>(null);
  const location = useLocation();

  // The phone settings menu closes when the desk moves to another page.
  useEffect(() => {
    setSettingsOpen(false);
  }, [location.pathname]);
  const {
    role,
    setRole,
    facility,
    setFacility,
    label,
    isPatient,
    myPatientId,
    demoSigninAllowed,
    signedInSubject,
    authMode,
    loadingAuth,
    deployment,
  } = useRole();

  // Sticky table headers sit just below the (wrapping) app header: publish its height.
  useEffect(() => {
    const header = headerRef.current;
    if (!header || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() => {
      root.style.setProperty("--app-header-h", `${Math.ceil(header.getBoundingClientRect().height)}px`);
    });
    observer.observe(header);
    return () => observer.disconnect();
  }, [loadingAuth]);

  if (loadingAuth) {
    return (
      <div className="app-loading">
        <p role="status">{t("shell.loading")}</p>
      </div>
    );
  }

  const nav: NavItem[] = isPatient
    ? [
        { to: "/my-record", key: "nav.myRecord", icon: "shield" },
        { to: "/visit", key: "nav.addNote", icon: "note" },
        { to: `/patients/${myPatientId}`, key: "nav.fullChart", icon: "folder" },
      ]
    : [
        { to: "/", key: "nav.queue", icon: "queue", end: true },
        { to: "/cases", key: "nav.cases", icon: "folder" },
        { to: "/reviews", key: "nav.reviews", icon: "check" },
        { to: "/patients", key: "nav.patients", icon: "users" },
        { to: "/visit", key: "nav.visit", icon: "note" },
      ];

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        {t("shell.skip")}
      </a>
      {deployment ? (
        <div
          className={`mode-banner mode-banner-${deployment.mode}`}
          role="status"
          aria-live="polite"
          data-mode={deployment.mode}
        >
          {deploymentBannerText(deployment)}
        </div>
      ) : null}

      <header className="app-header" ref={headerRef}>
        <NavLink to={isPatient ? "/my-record" : "/"} className="brand" end>
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <rect x="1" y="1" width="22" height="22" rx="6" />
              <path d="M7 12h10M12 7v10" />
            </svg>
          </span>
          <span className="brand-text">
            <strong>HealthEvidence AI</strong>
            <span>{t("shell.brandSub")}</span>
          </span>
        </NavLink>

        <button
          type="button"
          className="header-btn settings-toggle"
          aria-expanded={settingsOpen}
          aria-controls="desk-settings"
          onClick={() => setSettingsOpen((value) => !value)}
        >
          <Icon name="chevron-down" className={settingsOpen ? "is-flipped" : undefined} />
          <span>{t("shell.settings")}</span>
        </button>
        <div
          className={`header-tools${settingsOpen ? " is-open" : ""}`}
          id="desk-settings"
          onKeyDown={(event) => {
            if (event.key === "Escape" && settingsOpen) setSettingsOpen(false);
          }}
        >
          {demoSigninAllowed ? (
            <>
              {!isPatient ? (
                <label className="header-field">
                  <span className="header-field-label">{t("shell.facility")}</span>
                  <select
                    value={facility}
                    onChange={(event) => setFacility(event.target.value as FacilityType)}
                  >
                    {facilityOptions().map((item) => (
                      <option key={item.id} value={item.id}>
                        {t(`facility.${item.id}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="header-field">
                <span className="header-field-label">{t("shell.signIn")}</span>
                <select
                  value={role}
                  aria-label={t("shell.signIn")}
                  onChange={(event) => setRole(event.target.value as DeskRole)}
                >
                  {ROLE_IDS.map((id) => (
                    <option key={id} value={id}>
                      {t(`role.${id}` as MessageKey)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <p className="header-identity" title={`Auth: ${authMode}`}>
              <span className="header-field-label">{t("shell.signedIn")}</span>
              <strong>{signedInSubject || label}</strong>
            </p>
          )}

          <div className="lang-toggle" role="group" aria-label={t("shell.language")}>
            {LANGS.map((item) => (
              <button
                key={item.id}
                type="button"
                lang={item.id}
                aria-pressed={lang === item.id}
                className={lang === item.id ? "is-active" : undefined}
                onClick={() => setLang(item.id)}
                title={item.name}
              >
                {item.label}
              </button>
            ))}
          </div>
          <HelpChat />
        </div>
      </header>

      <div className="app-body">
        <nav className="app-nav" aria-label={t("nav.label")}>
          <ul>
            {nav.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end}>
                  <Icon name={item.icon} />
                  <span>{t(item.key)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <main className="app-main" id="main-content" tabIndex={-1}>
          <Routes>
            <Route
              path="/"
              element={isPatient ? <Navigate to="/my-record" replace /> : <WorkQueuePage mode="queue" />}
            />
            <Route
              path="/cases"
              element={isPatient ? <Navigate to="/my-record" replace /> : <WorkQueuePage mode="cases" />}
            />
            <Route
              path="/cases/:caseId"
              element={isPatient ? <Navigate to="/my-record" replace /> : <CaseWorkspacePage />}
            />
            <Route path="/my-record" element={<MyRecordPage />} />
            <Route
              path="/patients"
              element={isPatient ? <Navigate to="/my-record" replace /> : <PatientsPage />}
            />
            <Route path="/patients/:patientId" element={<PatientDetailPage />} />
            <Route path="/visit" element={<OpdIngestPage />} />
            <Route
              path="/reviews"
              element={isPatient ? <Navigate to="/my-record" replace /> : <ReviewsPage />}
            />
            <Route path="/encounter" element={<Navigate to="/visit" replace />} />
            <Route path="/opd" element={<Navigate to="/visit" replace />} />
            <Route path="/authorization" element={<Navigate to="/reviews" replace />} />
            <Route path="/today" element={<Navigate to="/" replace />} />
          </Routes>
          <footer className="app-footer">
            <p>{t("shell.footer")}</p>
          </footer>
        </main>
      </div>
    </div>
  );
}
