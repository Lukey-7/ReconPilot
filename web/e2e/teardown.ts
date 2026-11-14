/**
 * After the browser tests: Playwright stops the web server by killing it, which leaves its
 * embedded PostgreSQL running, so stop that too.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export default function teardown(): void {
  const dataDir = process.env.RP_E2E_DATA_DIR;
  if (!dataDir) return;
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
  const python =
    process.env.RP_E2E_PYTHON ??
    path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  try {
    execFileSync(python, [path.join(root, "scripts", "e2e_server.py"), "stop", "--data-dir", dataDir], {
      stdio: "inherit",
      timeout: 60_000,
    });
  } catch (error) {
    console.error("Could not stop the end-to-end database:", error);
  }
}
