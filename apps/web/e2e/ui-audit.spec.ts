import { expect, test } from '@playwright/test';
import path from 'node:path';

const adminPassword = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';
const auditRoot = path.resolve(process.cwd(), 'test-results/ui-audit');
const pages = [
  ['dashboard', '/'],
  ['workspace', '/workspace'],
  ['projects', '/projects'],
  ['tasks', '/tasks'],
  ['workers', '/workers'],
  ['sessions', '/sessions'],
  ['knowledge', '/knowledge'],
  ['settings', '/settings'],
  ['accounts-models', '/settings/accounts'],
  ['mcp', '/settings/mcp'],
  ['chat', '/sessions/audit-missing'],
  ['terminal', '/workspace'],
  ['files-git-diff', '/sessions/audit-missing/files'],
  ['subagents', '/agents'],
] as const;

test('audit all primary pages in the configured viewport and theme', async ({ page }, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(adminPassword);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();

  const theme = testInfo.project.name === 'audit-2560' ? 'dark' : 'light';
  await page.evaluate((value) => document.documentElement.setAttribute('data-theme', value), theme);
  for (const [name, route] of pages) {
    await page.goto(route);
    const heading = page.locator('main h1').first();
    if (!(await heading.isVisible().catch(() => false))) {
      testInfo.annotations.push({ type: 'missing-heading', description: `${name}: no visible main h1` });
    }
    await page.screenshot({
      path: path.join(auditRoot, `${testInfo.project.name}-${name}.png`),
      fullPage: true,
    });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    testInfo.annotations.push({ type: 'overflow', description: `${name}: ${overflow}px` });
  }
});
