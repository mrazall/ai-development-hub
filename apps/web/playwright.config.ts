import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

// Runs against an already started control-plane that serves apps/web/dist
// (dev: scripts/dev/dev-panel.sh on :58090; CI/stack: set AIHUB_E2E_BASE_URL).
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.AIHUB_E2E_BASE_URL ?? 'http://127.0.0.1:58090',
    // Specs select by the Russian source strings; the UI picks its language from the browser.
    locale: 'ru-RU',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      testIgnore: /critical\.spec\.ts|ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 860 } },
    },
    {
      name: 'critical',
      testMatch: /critical\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } },
    },
    {
      name: 'audit-1440',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, colorScheme: 'light' },
    },
    {
      name: 'audit-2560',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 2560, height: 1440 }, colorScheme: 'dark' },
    },
    {
      name: 'audit-375',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Pixel 5'], viewport: { width: 375, height: 812 }, colorScheme: 'light' },
    },
  ],
  outputDir: path.resolve(process.cwd(), 'e2e/test-results'),
});
