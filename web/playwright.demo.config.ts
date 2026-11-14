/**
 * The public demo's browser journey: the built front end served by the demo instance
 * (`reconpilot-web serve --mode demo`'s way: its own embedded PostgreSQL, the AI cache
 * loaded, a worker and the cleanup job in-process), started by scripts/e2e_server.py
 * serve-demo on a throwaway data folder. Build first: `npm run test:e2e:demo` does both.
 *
 * One worker and Chromium only, as for the other journeys; never run alongside them.
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
const port = Number(process.env.RP_E2E_DEMO_PORT ?? 8766);
const dataDir = process.env.RP_E2E_DEMO_DATA_DIR ?? path.join(os.tmpdir(), "reconpilot-e2e-demo");

// The teardown stops the database in this folder.
process.env.RP_E2E_DATA_DIR = dataDir;

export default defineConfig({
  testDir: "./e2e/demo",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
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
    command: `"${python}" "${path.join(root, "scripts", "e2e_server.py")}" serve-demo --data-dir "${dataDir}" --port ${port}`,
    url: `http://127.0.0.1:${port}/api/instance`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
