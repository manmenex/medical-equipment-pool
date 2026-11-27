import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/App";
import "@/index.css";
import { queryClient } from "@/lib/queryClient";
import { captureInstallPrompt, registerServiceWorker } from "@/offline/pwa";
import { applyPreferences, readCachedPreferences } from "@/lib/theme";
import { useUiStore } from "@/store/uiStore";

// Instant paint: this account's cached theme, else the legacy local light/dark choice.
applyPreferences(readCachedPreferences() ?? { mode: useUiStore.getState().theme });
captureInstallPrompt();
void registerServiceWorker().catch(() => undefined);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
