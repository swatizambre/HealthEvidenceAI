import { defineConfig, devices } from "@playwright/test";

const WEB = process.env.HE_WEB_BASE || "http://127.0.0.1:5173";
const API = process.env.HE_API_BASE || "http://127.0.0.1:8010";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: WEB,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command:
        "uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8010",
      cwd: "..",
      url: `${API}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        ENVIRONMENT: "local",
        AUTH_MODE: "dev-jwt",
        SEED_ON_STARTUP: "true",
        LLM_PROVIDER: "local",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      url: WEB,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
