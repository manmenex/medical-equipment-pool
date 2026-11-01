import { defineConfig } from "@playwright/test";

// PR25E E1: browser drills against the real backend (throwaway SQLite, synthetic
// fixtures) and the built frontend served by `vite preview` (which proxies
// /api to the backend, as in development). One worker, serial: the scenarios
// share one database and each uses equipment of its own.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    serviceWorkers: "allow",
    launchOptions: executablePath ? { executablePath } : {},
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "bash e2e/support/start-backend.sh",
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173/login",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
