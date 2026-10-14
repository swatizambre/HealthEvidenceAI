import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { I18nProvider } from "./i18n";
import { RealtimeProvider } from "./realtimeContext";
import { RoleProvider } from "./roleContext";
import { ToastProvider } from "./ui";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <RoleProvider>
          <RealtimeProvider>
            <ToastProvider>
              <App />
            </ToastProvider>
          </RealtimeProvider>
        </RoleProvider>
      </I18nProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
