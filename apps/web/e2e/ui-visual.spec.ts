import { expect, test } from '@playwright/test';

async function installVisualMocks(page: import('@playwright/test').Page): Promise<void> {
  await page.route('**/api/v0/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v0', '');
    const body =
      path === '/auth/login' || path === '/auth/refresh'
        ? { access_token: 'ui-audit-fixture-token' }
        : path === '/auth/me'
          ? { id: 'user-fixture', username: 'ui-audit', role: 'admin' }
          : path === '/dashboard'
            ? {
                projects: 0,
                tasks: {},
                workers: {},
                sessions: {},
                events: [],
                services: { api: 'ok', database: 'ok', knowledge: 'ok' },
              }
            : path === '/system/info'
              ? { demo: false }
              : path === '/health' || path === '/system/health'
                ? { errors: [] }
                : path === '/knowledge/graph'
                  ? { nodes: [], edges: [] }
                  : path.startsWith('/knowledge/documents')
                    ? { items: [], total: 0, offset: 0, limit: 50 }
                    : path.startsWith('/knowledge/search')
                      ? { hits: [] }
                      : path.startsWith('/knowledge/drafts')
                        ? { drafts: [] }
                        : [];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  // Playwright evaluates the most recently registered matching route first.
  await page.route('**/api/v0/events/stream**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': mock stream\n\n' }),
  );
}

test('critical route visual baselines', async ({ page }) => {
  await installVisualMocks(page);
  await page.goto('/login');
  await page.getByLabel(/Пользователь|User|Username/i).fill('ui-audit');
  await page.getByLabel(/Пароль|Password/i).fill('fixture-password');
  await page.getByRole('button', { name: /Войти|Sign in|Log in/i }).click();
  await expect(page.getByRole('navigation', { name: /Основная навигация|Main navigation/i })).toBeVisible();
  for (const route of ['/', '/workspace', '/projects', '/sessions', '/knowledge', '/settings']) {
    await page.goto(route);
    if (route === '/') {
      // The dashboard and stream are mocked above; wait for the fixture before capturing the full page.
      await expect(page.getByRole('region', { name: 'Ключевые показатели' })).toBeVisible();
    }
    await expect(page).toHaveScreenshot(
      `critical-${route === '/' ? 'dashboard' : route.slice(1).replaceAll('/', '-')}.png`,
      {
        animations: 'disabled',
        fullPage: true,
        caret: 'hide',
        mask: [page.locator('[data-testid="live-clock"]')],
      },
    );
  }
});
