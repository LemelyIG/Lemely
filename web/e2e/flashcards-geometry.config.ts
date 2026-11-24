import { defineConfig } from "@playwright/test"

// Deliberately independent of the database-backed acceptance configuration and global setup.
export default defineConfig({
  testDir: ".",
  testMatch: "flashcards-geometry.spec.ts",
  use: { baseURL: "http://127.0.0.1:5198", browserName: "chromium" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5198 --strictPort",
    url: "http://127.0.0.1:5198",
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
