import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { spawn, type ChildProcess } from 'node:child_process';

const adminPassword = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';

async function login(page: Page, password = adminPassword): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

type ApiInit = { method?: string; body?: unknown; headers?: Record<string, string> };
type EventRecord = { kind: string; payload?: Record<string, unknown> };

async function api<T>(page: Page, path: string, init: ApiInit = {}): Promise<T> {
  const token = await page.evaluate(() => sessionStorage.getItem('aihub.access_token'));
  const response = await page.request.fetch(`/api/v0${path}`, {
    method: init.method ?? 'GET',
    headers: { Authorization: `Bearer ${token}`, ...init.headers },
    data: init.body,
  });
  expect(response.ok(), `${init.method ?? 'GET'} ${path}: ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function createProject(page: Page, suffix = Date.now().toString(36)) {
  const id = `e2e-${suffix}`.slice(0, 63);
  return api<{ id: string; name: string; deleted_at?: string | null }>(page, '/projects', {
    method: 'POST',
    body: {
      id,
      name: `E2E ${suffix}`,
      visibility: 'private',
      allowed_paths: [resolve('e2e/test-results')],
      allowed_commands: [],
    },
  });
}

async function waitForEvent(page: Page, sessionId: string, predicate: (event: EventRecord) => boolean) {
  await expect
    .poll(
      async () => {
        const events = await api<EventRecord[]>(page, `/events?session_id=${encodeURIComponent(sessionId)}&limit=500`);
        return events.some(predicate);
      },
      { timeout: 30_000, intervals: [250, 500, 1_000] },
    )
    .toBeTruthy();
}

function startMockWorker(workerId: string, sessionId: string): ChildProcess {
  const root = resolve('..', '..');
  const workerScript = [
    'import asyncio, httpx',
    'from pathlib import Path',
    'from aihub_agents.worker import Worker',
    'async def run():',
    "    w = Worker('http://127.0.0.1:58094', '" +
      workerId +
      "', Path('e2e-worker-token').read_text(), enabled_engines={'mock'})",
    '    await w.capabilities()',
    '    async with httpx.AsyncClient() as client:',
    "        await w.run_assignment(client, {'id': '" + sessionId + "'})",
    'asyncio.run(run())',
  ].join('\n');
  const child = spawn(resolve(root, '.venv-dev-k/bin/python'), ['-c', workerScript], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: join(root, 'packages/agent-adapters') },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  child.stderr?.on('data', (chunk) => console.error(String(chunk)));
  return child;
}

test.describe('critical UI flows', { tag: '@critical' }, () => {
  test('shell uses the viewport and does not overflow at desktop or phone width', async ({ browser }) => {
    // Risk covered: a fixed-width shell makes the workspace unusable on desktop or mobile.
    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 375, height: 812 },
    ]) {
      const context = await browser.newContext({
        viewport,
        isMobile: viewport.width < 500,
        hasTouch: viewport.width < 500,
      });
      const page = await context.newPage();
      await login(page);
      await page.goto('/workspace');
      await expect(page.locator('main h1').first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      await context.close();
    }
  });

  test('workspace panel resize persists after reload', async ({ page }) => {
    await login(page);
    await page.goto('/workspace');
    const handle = page.getByRole('button', { name: 'Изменить размер панели' }).first();
    await expect(handle).toBeVisible();
    await handle.focus();
    await page.keyboard.press('End');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('aihub.workspace.sessions'))).toBe('460');
    await page.reload();
    await expect(page.locator('.workspace-grid')).toHaveAttribute('style', /--split-size: 460px/);
  });

  test('knowledge list, search narrowing, and clearing restore the list', async ({ page }) => {
    await login(page);
    await page.goto('/knowledge');
    const list = page.locator('.knowledge-hit');
    await expect(page.getByRole('heading', { name: 'База знаний' })).toBeVisible();
    await expect.poll(() => list.count(), { timeout: 10_000 }).toBeGreaterThan(0);
    const initialCount = await list.count();
    const search = page.getByLabel('Поиск по базе знаний');
    await search.fill('zzzz-e2e-no-match');
    await expect(page.getByText('Ничего не найдено')).toBeVisible();
    await search.fill('');
    await expect.poll(() => list.count(), { timeout: 5_000 }).toBe(initialCount);
  });

  test('attachment reaches the mock worker workdir', async ({ page }) => {
    await login(page);
    const project = await createProject(page, `attachment-${Date.now().toString(36)}`);
    const workerId = `e2e-worker-${Date.now().toString(36)}`;
    const worker = await api<{ worker_token: string }>(page, '/workers', {
      method: 'POST',
      body: { id: workerId, host: 'localhost', kind: 'e2e', labels: [], lease_ttl_s: 60 },
    });
    const task = await api<{ id: string }>(page, `/projects/${project.id}/tasks`, {
      method: 'POST',
      body: { title: 'Attachment smoke', body: 'attachment smoke prompt', idempotency_key: crypto.randomUUID() },
    });
    const session = await api<{ id: string }>(page, '/sessions', {
      method: 'POST',
      body: {
        task_id: task.id,
        project_id: project.id,
        worker_id: workerId,
        engine: 'mock_echo_prompt',
        provider: 'mock',
        model: 'mock',
        auth_mode: 'none',
        workdir: resolve('e2e/test-results'),
        title: 'Attachment smoke',
      },
    });
    await page.goto(`/workspace?project=${project.id}&session=${session.id}`);
    const png = Buffer.from('89504e470d0a1a0a', 'hex');
    await page.locator('input[type=file]').setInputFiles({ name: 'e2e.png', mimeType: 'image/png', buffer: png });
    await expect(page.getByText('e2e.png')).toBeVisible();
    const attachment = (await api<{ id: string }[]>(page, `/sessions/${session.id}/attachments`))[0];
    await api(page, `/sessions/${session.id}/events`, {
      method: 'POST',
      body: [{ kind: 'message', payload: { role: 'user', text: 'check attachment', attachment_ids: [attachment.id] } }],
    });
    const tokenFile = resolve('../..', 'e2e-worker-token');
    const { writeFileSync, unlinkSync } = await import('node:fs');
    writeFileSync(tokenFile, worker.worker_token, { mode: 0o600 });
    let process: ChildProcess | undefined;
    try {
      process = startMockWorker(workerId, session.id);
      await waitForEvent(
        page,
        session.id,
        (event) =>
          event.kind === 'message' &&
          typeof event.payload?.text === 'string' &&
          event.payload.text.includes('.aihub/attachments/'),
      );
      const events = await api<EventRecord[]>(page, `/events?session_id=${session.id}&limit=500`);
      const message = events.find(
        (event) =>
          event.kind === 'message' &&
          typeof event.payload?.text === 'string' &&
          event.payload.text.includes('.aihub/attachments/'),
      );
      expect(message?.payload?.text).toContain('.aihub/attachments/');
    } finally {
      process?.kill('SIGTERM');
      unlinkSync(tokenFile);
    }
  });

  test('project archive, restore, and confirmed soft-delete preserve the repository', async ({ page }) => {
    await login(page);
    const project = await createProject(page, `lifecycle-${Date.now().toString(36)}`);
    const repo = join(resolve('e2e/test-results'), `${project.id}-repo`);
    mkdirSync(repo, { recursive: true });
    await page.goto(`/projects/${project.id}`);
    await page.getByRole('button', { name: 'Архивировать' }).click();
    await expect(page.getByText('В архиве')).toBeVisible();
    await page.getByRole('button', { name: 'Восстановить' }).click();
    await expect(page.getByRole('button', { name: 'Архивировать' })).toBeVisible();
    await page.getByRole('button', { name: 'Удалить', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Удалить проект?' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Репозиторий, файлы, vault и бэкапы не удаляются');
    await dialog.getByRole('textbox').fill(project.name);
    await dialog.getByRole('button', { name: 'Удалить проект' }).click();
    await expect(page).toHaveURL(/\/projects$/);
    expect(existsSync(repo)).toBeTruthy();
    const deleted = await api<{ deleted_at: string | null }>(page, `/projects/${project.id}`);
    expect(deleted.deleted_at).toBeTruthy();
  });

  test('keyboard focus reaches navigation and Escape closes the session dialog', async ({ page }) => {
    await login(page);
    await page.goto('/workspace');
    await page.getByRole('button', { name: '+ Новая сессия' }).click();
    const dialog = page.getByRole('dialog').filter({ hasText: 'Новая сессия' });
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await page.keyboard.press('Tab');
    await expect(page.locator(':focus-visible')).toHaveCount(1);
  });
});
