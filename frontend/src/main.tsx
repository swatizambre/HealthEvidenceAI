import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { I18nProvider } from "./i18n";
import { PublicEmergencyPage } from "./pages/PublicEmergency";
import { RealtimeProvider } from "./realtimeContext";
import { RoleProvider } from "./roleContext";
import { ToastProvider } from "./ui";
import "./styles.css";

function Desk() {
  return (
    <I18nProvider>
      <RoleProvider>
        <RealtimeProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </RealtimeProvider>
      </RoleProvider>
    </I18nProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Opened from a patient's emergency QR: no sign-in, no app chrome. */}
        <Route path="/e/:token" element={<PublicEmergencyPage />} />
        <Route path="*" element={<Desk />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);

// Keep the app shell available offline so the emergency card opens with no signal.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is best-effort */
    });
  });
}
