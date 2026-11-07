import { defineConfig, devices } from "@playwright/test";

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "tests/e2e-browser",
  timeout: 60_000,
  retries: isCI ? 1 : 0,
  reporter: isCI ? [["junit"], ["list"]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.APP_URL ?? "http://localhost:8501",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // 1. Sacrificial HS-code target
      command:
        "uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001",
      port: 8001,
      env: {
        HS_TARGET_API_KEY: "test-key-123",
        HS_TARGET_CANARY: "KESTREL-CANARY-demo",
      },
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
    {
      // 2. Kestrel API
      command:
        "uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000",
      port: 8000,
      env: { KESTREL_MODE: "local" },
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
    {
      // 3. Streamlit UI
      command:
        "uv run streamlit run ui/app.py --server.headless true --server.port 8501",
      url: "http://localhost:8501",
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
  ],
});