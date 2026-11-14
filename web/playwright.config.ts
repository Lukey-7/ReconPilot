/**
 * Browser tests: the real API, worker and built front end (`reconpilot-web serve`'s way of
 * serving web/dist, so the CSP and security headers apply) on a throwaway embedded
 * PostgreSQL, started by scripts/e2e_server.py. Build first: `npm run test:e2e` does both.
 *
 * One worker and Chromium only: the journeys share one database and run in order, and the
 * machine this was written on has little memory to spare.
 */
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const python =
  process.env.RP_E2E_PYTHON ??
  path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const port = Number(process.env.RP_E2E_PORT ?? 8765);
const dataDir = process.env.RP_E2E_DATA_DIR ?? path.join(os.tmpdir(), "reconpilot-e2e");

// The tests read these too (they run in workers that load this file).
process.env.RP_E2E_DATA_DIR = dataDir;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  globalTeardown: "./e2e/teardown.ts",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    locale: "en-GB",
    timezoneId: "Europe/London",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `"${python}" "${path.join(root, "scripts", "e2e_server.py")}" serve --data-dir "${dataDir}" --port ${port}`,
    url: `http://127.0.0.1:${port}/api/auth/me`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
