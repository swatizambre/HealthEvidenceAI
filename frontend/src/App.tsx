import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { FOOTER_DISCLAIMER } from "./api";
import { HelpChat } from "./components/HelpChat";
import { facilityOptions, useRole, type DeskRole, type FacilityType } from "./roleContext";
import { AuthorizationPage } from "./pages/Authorization";
import { DashboardPage } from "./pages/Dashboard";
import { MyRecordPage } from "./pages/MyRecord";
import { OpdIngestPage } from "./pages/OpdIngest";
import { PatientDetailPage } from "./pages/PatientDetail";
import { PatientsPage } from "./pages/Patients";

export function App() {
  const {
    role,
    setRole,
    facility,
    setFacility,
    label,
    facilityLabel,
    isPatient,
    myPatientId,
    demoSigninAllowed,
    signedInSubject,
    authMode,
    loadingAuth,
  } = useRole();

  if (loadingAuth) {
    return (
      <div className="app-shell app-shell-loading">
        <p className="muted pulse" role="status">
          Signing in to the evidence desk…
        </p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand" end>
            <span className="brand-mark" aria-hidden="true" />
            <span className="brand-text">
              <strong>HealthEvidence AI</strong>
              <em>Evidence desk · lifelong chart</em>
            </span>
          </NavLink>
          <nav className="top-nav" aria-label="Application">
            {isPatient ? (
              <>
                <NavLink to="/my-record">My record</NavLink>
                <NavLink to="/visit">Add note</NavLink>
                <NavLink to={`/patients/${myPatientId}`}>Full chart</NavLink>
              </>
            ) : (
              <>
                <NavLink to="/" end>
                  Today
                </NavLink>
                <NavLink to="/reviews">Reviews</NavLink>
                <NavLink to="/patients">Patients</NavLink>
                <NavLink to="/visit">Visit note</NavLink>
              </>
            )}
          </nav>
          <div className="desk-switches">
            {demoSigninAllowed ? (
              <>
                <label className="role-switch">
                  <span className="sr-only">Facility type</span>
                  <select
                    value={facility}
                    onChange={(event) => setFacility(event.target.value as FacilityType)}
                    aria-label="Facility type"
                    title={`Desk: ${facilityLabel}`}
                  >
                    {facilityOptions().map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="role-switch">
                  <span className="sr-only">Demo sign-in</span>
                  <select
                    value={role}
                    onChange={(event) => setRole(event.target.value as DeskRole)}
                    aria-label="Demo sign-in"
                    title={`Demo sign-in as ${label}`}
                  >
                    <option value="patient">Patient (my record)</option>
                    <option value="staff">Records / TPA desk clerk</option>
                    <option value="resident">Junior doctor / PG / MO (junior)</option>
                    <option value="senior_clinician">Consultant / senior MO</option>
                    <option value="admin">Facility / HIS admin</option>
                  </select>
                </label>
              </>
            ) : (
              <p className="signed-in-chip" title={`Auth: ${authMode}`}>
                {signedInSubject || label}
              </p>
            )}
          </div>
        </div>
      </header>
      <main className="content" id="main-content">
        <Routes>
          <Route
            path="/"
            element={isPatient ? <Navigate to="/my-record" replace /> : <DashboardPage />}
          />
          <Route path="/my-record" element={<MyRecordPage />} />
          <Route
            path="/patients"
            element={isPatient ? <Navigate to="/my-record" replace /> : <PatientsPage />}
          />
          <Route
            path="/patients/:patientId"
            element={<PatientDetailPage />}
          />
          <Route path="/visit" element={<OpdIngestPage />} />
          <Route
            path="/reviews"
            element={isPatient ? <Navigate to="/my-record" replace /> : <AuthorizationPage />}
          />
          <Route path="/encounter" element={<Navigate to="/visit" replace />} />
          <Route path="/opd" element={<Navigate to="/visit" replace />} />
          <Route path="/authorization" element={<Navigate to="/reviews" replace />} />
        </Routes>
      </main>
      <footer className="app-footer">
        <p>{FOOTER_DISCLAIMER}</p>
      </footer>
      <HelpChat />
    </div>
  );
}
