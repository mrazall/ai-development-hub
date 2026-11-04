import { expect, test } from '@playwright/test';

// After a deploy an open page asks for bundle files that no longer exist. It used to fall into an empty grey
// screen until a manual reload; now it reloads once by itself, and a page that still throws shows a way out.
// The service worker would fetch bundle files itself, out of reach of page.route.
test.use({ serviceWorkers: 'block' });

async function signIn(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

test('устаревший кусок страницы после деплоя: одна перезагрузка, и страница открывается', async ({ page }) => {
  let missing = true;
  // Before signing in: the chunk must not be cached from an earlier load.
  await page.route(/\/assets\/Stats-[^/]+\.js$/, (route) => {
    if (missing) {
      missing = false;
      return route.fulfill({ status: 404, body: 'gone' });
    }
    return route.continue();
  });
  await signIn(page);
  let documents = 0;
  page.on('request', (request) => {
    if (request.resourceType() === 'document') documents += 1;
  });
  await page.locator('nav a[href="/stats"]').first().click();
  await expect(page.getByRole('heading', { name: 'Статистика' })).toBeVisible();
  expect(missing).toBe(false);
  expect(documents).toBe(1); // exactly one reload fetched the new bundle
});

test('сломанная страница показывает ошибку и выход, а не пустой экран', async ({ page }) => {
  const reported: string[] = [];
  await page.route('**/api/v0/client-errors', (route) => {
    reported.push(route.request().postData() ?? '');
    return route.fulfill({ status: 204 });
  });
  await signIn(page);
  // A response the page does not expect (the shape that crashed the dashboard on a phone).
  await page.route('**/api/v0/dashboard**', (route) => route.fulfill({ json: { workers: null } }));
  await page.goto('/');
  await expect(page.getByRole('alert').getByText('Эта страница сломалась')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Обновить страницу' })).toBeVisible();
  // The rest of the panel still works: navigation leads to a fresh page.
  await page.locator('nav a[href="/tasks"]').first().click();
  await expect(page.getByRole('alert').getByText('Эта страница сломалась')).toHaveCount(0);
  expect(reported.some((body) => body.includes('"where":"page"'))).toBe(true);
});
