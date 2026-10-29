import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Credentials of throwaway test users (dev: scripts/dev/.dev-users; CI: generated per run).
const adminPassword = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';
const viewerPassword = process.env.AIHUB_E2E_VIEWER_PASSWORD ?? '';
const run = Date.now().toString(36);
const shots = 'e2e/screenshots';

test.beforeAll(() => {
  expect(adminPassword, 'AIHUB_E2E_ADMIN_PASSWORD is required').not.toBe('');
  expect(viewerPassword, 'AIHUB_E2E_VIEWER_PASSWORD is required').not.toBe('');
});

async function login(page: Page, username: string, password: string): Promise<void> {
  // A render crash leaves a blank page; surface the exception instead of a vague 'not visible'.
  page.on('pageerror', (error) =>
    console.log(`PAGEERROR ${error.message}
${error.stack ?? ''}`),
  );
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill(username);
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  // Signed in = the main navigation is rendered (the landing page may change).
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

async function apiToken(request: APIRequestContext, username: string, password: string): Promise<string> {
  const response = await request.post('/api/v0/auth/login', { data: { username, password } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).access_token as string;
}

const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });

async function ensureProject(request: APIRequestContext, token: string, id: string, visibility = 'private') {
  const response = await request.post('/api/v0/projects', {
    headers: bearer(token),
    data: { id, name: id, visibility },
  });
  expect([201, 409]).toContain(response.status());
}

test('@smoke admin creates a project through the form and the dashboard counts it', async ({ page }) => {
  await login(page, 'admin', adminPassword);
  const before = Number(await page.locator('.stat-card').first().locator('strong').innerText());
  await page.screenshot({ path: `${shots}/dashboard.png`, fullPage: true });

  await page.goto('/projects');
  const id = `e2e-${run}`;
  // Creation lives in a dialog opened from the page header.
  await page.getByRole('button', { name: /Новый проект/ }).click();
  await page.getByLabel('ID проекта').fill(id);
  await page.getByLabel('Название').fill(`E2E ${run}`);
  await page.getByRole('button', { name: 'Создать' }).click();
  await expect(page.getByText(`E2E ${run}`)).toBeVisible();
  await page.screenshot({ path: `${shots}/projects.png`, fullPage: true });

  await page.goto('/');
  await expect(page.locator('.stat-card').first().locator('strong')).toHaveText(String(before + 1));
  const items = await page.locator('.event-list li').allInnerTexts();
  expect(new Set(items).size, 'dashboard events must not repeat').toBe(items.length);
});

test('admin creates a task and changes its status', async ({ page, request }) => {
  const token = await apiToken(request, 'admin', adminPassword);
  const project = `tasks-${run}`;
  await ensureProject(request, token, project);
  await login(page, 'admin', adminPassword);
  await page.goto(`/tasks?project=${project}`);
  await page.getByLabel('Название').fill('Проверить панель');
  await page.getByRole('button', { name: 'Создать задачу' }).click();
  await expect(page.getByText('Проверить панель')).toBeVisible();
  await page.getByLabel('Статус задачи Проверить панель').selectOption('in_progress');
  await expect
    .poll(async () => {
      const tasks = await (await request.get(`/api/v0/projects/${project}/tasks`, { headers: bearer(token) })).json();
      return tasks[0]?.status;
    })
    .toBe('in_progress');
  await page.screenshot({ path: `${shots}/tasks.png`, fullPage: true });
});

test('worker registration shows the token exactly once', async ({ page }) => {
  await login(page, 'admin', adminPassword);
  await page.goto('/workers');
  await page.getByLabel('ID').fill(`worker-e2e-${run}`);
  await page.getByLabel('Хост').fill('my-pc');
  await page.getByLabel('Метки').fill('gpu, wsl2');
  await page.getByRole('button', { name: 'Зарегистрировать' }).click();
  await expect(page.getByText('показывается один раз')).toBeVisible();
  await expect(page.locator('code.secret')).not.toBeEmpty();
  await page.getByRole('button', { name: 'Я сохранил токен' }).click();
  await expect(page.locator('code.secret')).toHaveCount(0);
  await expect(page.getByRole('cell', { name: new RegExp(`worker-e2e-${run}`) })).toBeVisible();
  await page.screenshot({ path: `${shots}/workers.png`, fullPage: true });
});

test('@smoke session page receives a live event over SSE', async ({ page, request }) => {
  const token = await apiToken(request, 'admin', adminPassword);
  const project = `live-${run}`;
  await ensureProject(request, token, project);
  const session = await (
    await request.post('/api/v0/sessions', {
      headers: bearer(token),
      data: {
        project_id: project,
        worker_id: 'worker-e2e',
        engine: 'codex',
        provider: 'openai',
        model: 'gpt-5.6-luna',
        auth_mode: 'subscription',
        workdir: '/home/dev/wt/demo',
        branch: 'main',
      },
    })
  ).json();

  await login(page, 'admin', adminPassword);
  await page.goto(`/sessions/${session.id}`);
  await expect(page.getByText('Источник статуса')).toBeVisible();
  await expect(page.getByText('Событий пока нет.')).toBeVisible();
  const posted = await request.post(`/api/v0/sessions/${session.id}/events`, {
    headers: bearer(token),
    data: [{ kind: 'output', payload: { text: `hello from e2e ${run}` } }],
  });
  expect(posted.ok()).toBeTruthy();
  await expect(page.getByLabel('Журнал событий сессии').getByText(`hello from e2e ${run}`)).toBeVisible({
    timeout: 10_000,
  });
  await page.screenshot({ path: `${shots}/session.png`, fullPage: true });

  await page.goto('/sessions');
  await expect(page.getByRole('link', { name: project })).toBeVisible();
  await page.screenshot({ path: `${shots}/sessions.png`, fullPage: true });
});

test('@smoke workspace selects a project and creates a session', async ({ page, request }) => {
  const token = await apiToken(request, 'admin', adminPassword);
  const project = `workspace-${run}`;
  await ensureProject(request, token, project);
  await login(page, 'admin', adminPassword);
  await page.goto('/workspace');
  await page.getByRole('button', { name: new RegExp(project) }).click();
  await page.getByRole('button', { name: '+ Новая сессия' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Проект').selectOption(project);
  await dialog.getByLabel('Задача / промпт').fill('Smoke: опиши структуру проекта');
  await dialog.getByRole('button', { name: 'Запустить' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(project).first()).toBeVisible();
});

test('@smoke viewer sees no write controls', async ({ page }) => {
  await login(page, 'viewer', viewerPassword);
  await page.goto('/projects');
  await expect(page.getByRole('button', { name: 'Создать' })).toHaveCount(0);
  await page.goto('/workers');
  await expect(page.getByRole('button', { name: 'Зарегистрировать' })).toHaveCount(0);
  // Server-side refusal (403) is covered by control-plane RBAC integration tests.
});

test('knowledge page reports an unavailable search backend instead of failing', async ({ page }) => {
  await login(page, 'admin', adminPassword);
  await page.goto('/knowledge');
  // Search runs as you type; with or without the knowledge service the page must show a list, a result
  // set, an empty state or an error banner — never a blank screen.
  await page.getByLabel('Поиск по базе знаний').fill('резервное копирование');
  await expect(page.locator('.error-banner, .knowledge-list-pane, .ui-empty, .empty').first()).toBeVisible();
  await page.screenshot({ path: `${shots}/knowledge.png`, fullPage: true });
});

test('mobile layout: navigation reachable, no horizontal scroll', async ({ browser }) => {
  // Smoke risk: the compact workspace/session list must remain usable at the minimum supported phone width.
  const context = await browser.newContext({ viewport: { width: 375, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  await login(page, 'admin', adminPassword);
  // Without <meta name="viewport"> phones lay the page out at 980 px and the overflow check passes vacuously.
  expect(await page.evaluate(() => document.documentElement.clientWidth)).toBe(375);
  for (const path of ['/', '/projects', '/tasks', '/workers', '/sessions', '/knowledge', '/settings']) {
    await page.goto(path);
    // Not 'networkidle': pages with a live SSE stream never go idle.
    await expect(page.locator('main h1').first()).toBeVisible();
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
    const name = path === '/' ? 'dashboard' : path.slice(1);
    await page.screenshot({ path: `${shots}/mobile-${name}.png`, fullPage: true });
  }
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await context.close();
});
