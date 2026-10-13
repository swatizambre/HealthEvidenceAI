import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { RealtimeProvider } from "./realtimeContext";
import { RoleProvider } from "./roleContext";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <RoleProvider>
        <RealtimeProvider>
          <App />
        </RealtimeProvider>
      </RoleProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
