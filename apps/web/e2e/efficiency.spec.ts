import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const summary = JSON.parse(
  readFileSync(fileURLToPath(new URL('./fixtures/efficiency-summary.json', import.meta.url)), 'utf8'),
);
const tasks = JSON.parse(
  readFileSync(fileURLToPath(new URL('./fixtures/efficiency-tasks.json', import.meta.url)), 'utf8'),
);

test('эффективность: показатели, фильтр, сортировка и детали', async ({ page }) => {
  const password = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';
  await page.route('**/api/v0/stats/efficiency**', (route) => route.fulfill({ json: summary }));
  await page.route('**/api/v0/stats/tasks**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/task-a')) {
      return route.fulfill({ json: { ...tasks.items[0], participants: [], runs: [], warnings: [], observations: [] } });
    }
    const items = url.searchParams.get('order') === 'asc' ? [...tasks.items].reverse() : tasks.items;
    return route.fulfill({ json: { ...tasks, items } });
  });
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.goto('/stats');
  const tab = page
    .getByRole('button', { name: /Эффективность/i })
    .or(page.getByRole('tab', { name: /Эффективность/i }));
  await tab.first().click();
  await expect(page.getByTestId('efficiency-kpi').getByText('1.2 k').first()).toBeVisible();
  await expect(page.getByText('—').first()).toBeVisible();
  await expect(page.getByText(/частич|неоцен/i).first()).toBeVisible();
  const periodRequest = page.waitForRequest(
    (request) => request.url().includes('/stats/efficiency') && new URL(request.url()).searchParams.get('days') === '7',
  );
  await page.getByRole('group', { name: 'Период' }).getByRole('button', { name: '7 дней' }).click();
  await periodRequest;
  const sortRequest = page.waitForRequest(
    (request) => request.url().includes('/stats/tasks') && new URL(request.url()).searchParams.get('sort') === 'tokens',
  );
  await page.getByTestId('efficiency-tasks').getByRole('button', { name: 'Токены' }).click();
  await sortRequest;
  await page.getByTestId('efficiency-tasks').getByRole('button', { name: 'Альфа' }).click();
  await expect(page.getByTestId('efficiency-task-detail').getByText('Альфа', { exact: true })).toBeVisible();
});
