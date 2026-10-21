import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/App";
import "@/index.css";
import { queryClient } from "@/lib/queryClient";
import { captureInstallPrompt, registerServiceWorker } from "@/offline/pwa";
import { applyTheme, useUiStore } from "@/store/uiStore";

applyTheme(useUiStore.getState().theme);
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
