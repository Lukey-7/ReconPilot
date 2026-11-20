import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API runs on 127.0.0.1:8000 (`reconpilot-web dev`); the dev server proxies /api to it,
// so the session and CSRF cookies are first-party for the page.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
    // A test renders the whole app; its finds wait up to 4 s each (see src/test/setup.ts).
    testTimeout: 15_000,
  },
});
