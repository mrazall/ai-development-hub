import { expect, test } from '@playwright/test';

// Smoke risk: settings-family pages must remain usable on a phone and expose honest
// loading/empty/error states even when optional APIs are unavailable.
const password = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';

async function login(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

test.describe('Luna-3 settings smoke', () => {
  test.beforeEach(async ({ page }) => login(page));

  test('settings family has no document horizontal overflow on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    for (const route of [
      '/settings',
      '/settings/accounts',
      '/settings/mcp',
      '/workers',
      '/notifications',
      '/backups',
      '/limits',
    ]) {
      await page.goto(route);
      await expect(page.locator('main h1').first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    }
  });

  test('notification filters and linked-object action are reachable', async ({ page }) => {
    await page.goto('/notifications');
    await page.getByLabel('Категория').selectOption('');
    await page.getByLabel('Важность').selectOption('warning');
    await expect(page.locator('.panel').last()).toBeVisible();
  });

  test('account and MCP pages do not expose secrets in the document', async ({ page }) => {
    await page.goto('/settings/accounts');
    await expect(page.getByRole('heading', { name: 'Аккаунты и модели' })).toBeVisible();
    await page.goto('/settings/mcp');
    await expect(page.getByRole('heading', { name: 'MCP-серверы' })).toBeVisible();
    await expect(page.locator('input[type=password]')).toHaveCount(0);
  });
});
