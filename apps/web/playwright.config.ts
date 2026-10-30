import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

// Runs against an already started control-plane that serves apps/web/dist
// (dev: scripts/dev/dev-panel.sh on :58090; CI/stack: set AIHUB_E2E_BASE_URL).
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: true,
  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: process.env.AIHUB_E2E_BASE_URL ?? 'http://127.0.0.1:58090',
    // Specs select by the Russian source strings; the UI picks its language from the browser.
    locale: 'ru-RU',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    timezoneId: 'UTC',
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
    {
      name: 'ui-smoke-375',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 375, height: 812 }, colorScheme: 'light', locale: 'ru-RU' },
    },
    {
      name: 'ui-smoke-1366',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 }, colorScheme: 'light', locale: 'ru-RU' },
    },
    {
      name: 'ui-smoke-1920',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 }, colorScheme: 'dark', locale: 'en-US' },
    },
    ...[
      [390, 844, 'light', 'ru-RU'], [768, 1024, 'dark', 'ru-RU'], [1024, 768, 'light', 'en-US'],
      [1280, 720, 'dark', 'en-US'], [1440, 900, 'light', 'ru-RU'], [2560, 1440, 'dark', 'en-US'],
    ].map(([width, height, colorScheme, locale]) => ({
      name: `ui-extended-${width}x${height}`,
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: Number(width), height: Number(height) }, colorScheme: colorScheme as 'light' | 'dark', locale: String(locale) },
    })),
    {
      name: 'audit-emulation-font-20px',
      testMatch: /ui-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 860 }, colorScheme: 'light', locale: 'ru-RU' },
    },
    ...[1.25, 1.5, 2].map((zoom) => ({
      name: `audit-emulation-zoom-${zoom * 100}%`,
      testMatch: /ui-audit\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        // A deterministic zoom-like emulation: preserve physical density while reducing CSS width.
        viewport: { width: Math.round(1366 / zoom), height: Math.round(860 / zoom) },
        deviceScaleFactor: zoom,
        colorScheme: 'light' as const,
        locale: 'ru-RU',
      },
    })),
  ],
  outputDir: path.resolve(process.cwd(), 'e2e/test-results'),
});
