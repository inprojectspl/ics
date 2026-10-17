import { defineConfig, devices } from "@playwright/test";

// E2E smoke tests for critical flows against a running stack: the Vite dev
// server (specs import modules from /src) with /api proxied to the backend.
// Locally that is `make dev`; the `e2e` CI job starts the backend and Vite
// next to Postgres and Redis services, see .github/workflows/ci.yml.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // shared session/cookie state breaks under parallel runs
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? "list" : "html",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    // Specs select by English labels; the UI follows the browser language.
    locale: "en-US",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
