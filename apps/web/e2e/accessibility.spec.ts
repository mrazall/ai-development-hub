import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('axe scan records serious and critical violations without failing CI', async ({ page }, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.goto('/workspace');
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  testInfo.annotations.push({ type: 'axe-serious-critical', description: JSON.stringify(serious) });
  expect(serious).toBeDefined();
});
