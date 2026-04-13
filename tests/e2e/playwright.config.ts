import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "../..");
const exampleServerDir = path.resolve(repoRoot, "examples/server");
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./specs",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  ...(isCI ? { workers: 1 } : {}),
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: process.env.TEST_BASE_URL || "http://127.0.0.1:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "./.venv/bin/uvicorn voice_chess_example_server.main:app --host 127.0.0.1 --port 7860",
      cwd: exampleServerDir,
      url: "http://127.0.0.1:7860/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "pnpm --filter @voice-chess/example-web exec vite --host 127.0.0.1 --port 5173",
      cwd: repoRoot,
      url: process.env.TEST_BASE_URL || "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
