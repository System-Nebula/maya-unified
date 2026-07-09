import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.MAYA_GATEWAY_PORT ?? 8765);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const USE_UNIFIED_GATEWAY = process.env.MAYA_E2E_UNIFIED === "1";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  webServer: {
    command: USE_UNIFIED_GATEWAY
      ? `MAYA_E2E_FIXTURES=1 PORT=${PORT} uv run python launch.py`
      : `uv run --quiet maya-gateway`,
    cwd: "../..",
    url: `${BASE_URL}/`,
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
    env: {
      PORT: String(PORT),
      ENV: "production",
    },
    stdout: "pipe",
    stderr: "pipe",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
