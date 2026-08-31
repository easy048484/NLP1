import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppProvider } from "./lib/appState";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./components/ui/ui.css";
import "./styles/screens.css";
import "./styles/site.css";
import "./styles/app-theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppProvider>
        <App />
      </AppProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
