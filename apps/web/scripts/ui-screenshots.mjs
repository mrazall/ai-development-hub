// UI walkthrough screenshots against the local dev panel (scripts/dev/dev-panel.sh, :58090).
// usage (WSL, from apps/web so @playwright/test resolves):
//   node scripts/ui-screenshots.mjs <out-dir>
// Logs in with the local admin from scripts/dev/.dev-users, visits every top-level route at a desktop
// and a phone size, saves full-page PNGs and prints one line per page with layout red flags.
import { readFileSync, mkdirSync } from 'node:fs';
import { chromium } from '@playwright/test';

const base = process.env.AIHUB_DEV_URL ?? 'http://127.0.0.1:58090';
const out = process.argv[2] ?? 'screenshots';
const creds = Object.fromEntries(
  readFileSync(process.env.AIHUB_DEV_CREDS ?? new URL('../../../scripts/dev/.dev-users', import.meta.url), 'utf8')
    .split('\n')
    .filter((line) => line.includes('='))
    .map((line) => line.trim().split('=')),
);
const routes = [
  '/',
  '/workspace',
  '/chats',
  '/projects',
  '/tasks',
  '/agents',
  '/knowledge',
  '/notifications',
  '/sessions',
  '/workers',
  '/limits',
  '/backups',
  '/settings',
  '/settings/accounts',
  '/settings/mcp',
  '/settings/users',
  '/settings/projects',
  '/settings/workers',
  '/settings/sessions',
];
const sizes = [
  ['phone-375', 375, 812],
  ['phone-430', 430, 932],
  ['tablet-768', 768, 1024],
  ['desktop-1440', 1440, 900],
  ['desktop-1920', 1920, 1080],
  ['desktop-2560', 2560, 1440],
];

mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [label, width, height] of sizes) {
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto(`${base}/login`);
  await page.locator('input').first().fill('admin');
  await page.locator('input[type=password]').fill(creds.admin);
  await page.locator('form button').first().click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  for (const route of routes) {
    const errors = [];
    page.removeAllListeners('pageerror');
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`${base}${route}`, { waitUntil: 'load' }).catch(() => {});
    await page.waitForTimeout(1500);
    const facts = await page.evaluate(() => ({
      hScroll: document.scrollingElement.scrollWidth - innerWidth,
      vScroll: document.scrollingElement.scrollHeight - innerHeight,
      errorBanners: document.querySelectorAll('.ui-error').length,
    }));
    const name = `${label}${route === '/' ? '-dashboard' : route.replaceAll('/', '-')}.png`;
    await page.screenshot({ path: `${out}/${name}`, fullPage: true });
    console.log(
      `${label} ${route} hScroll=${facts.hScroll} vScroll=${facts.vScroll} errors=${facts.errorBanners} jsErrors=${errors.length}`,
    );
  }
  await page.close();
}
await browser.close();
