import { expect, test } from '@playwright/test';

// The project's Files page: the worker is played by route fixtures (list/read answered through the requests API).
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

test('файлы проекта: сначала папка агента, картинка открывается, можно уйти в папку проекта', async ({ page }) => {
  const asked: { op: string; path: string }[] = [];
  const answers = new Map<string, unknown>();
  await page.route('**/api/v0/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v0', '');
    const json = (value: unknown) => route.fulfill({ json: value });
    if (path === '/auth/login' || path === '/auth/refresh') return json({ access_token: 'fixture' });
    if (path === '/auth/me') return json({ id: 'u1', username: 'admin', role: 'admin' });
    if (path === '/events/stream-ticket') return json({ ticket: 'fixture' });
    if (path === '/projects') return json([{ id: 'demo', name: 'Demo', visibility: 'shared', allowed_paths: [] }]);
    if (path === '/projects/demo')
      return json({ id: 'demo', name: 'Demo', visibility: 'shared', allowed_paths: ['/srv/demo'] });
    if (path === '/projects/demo/files') {
      const body = route.request().postDataJSON() as { op: string; path: string };
      asked.push(body);
      const id = `r${asked.length}`;
      const entry = (name: string, dir: boolean, size: number | null) => ({
        name,
        path: body.path ? `${body.path}/${name}` : name,
        dir,
        size,
        updated_at: '2026-11-04T10:04:00Z',
      });
      answers.set(
        id,
        body.op === 'read'
          ? {
              status: 'completed',
              result: { path: body.path, size: 68, mime: 'image/png', updated_at: '', base64: PNG },
            }
          : body.path === '.aihub/share'
            ? {
                status: 'completed',
                result: { path: '.aihub/share', share: '.aihub/share', entries: [entry('login.png', false, 68)] },
              }
            : {
                status: 'completed',
                result: {
                  path: '',
                  share: '.aihub/share',
                  entries: [entry('.aihub', true, null), entry('src', true, null)],
                },
              },
      );
      return json({ request_id: id });
    }
    if (path.startsWith('/files/requests/')) return json(answers.get(path.split('/').pop() ?? ''));
    return json([]);
  });
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill('fixture');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.goto('/projects/demo/files');
  const list = page.getByRole('list', { name: 'Файлы' });
  await expect(list.getByRole('button', { name: /login\.png/ })).toBeVisible();
  expect(asked.slice(0, 2)).toEqual([
    { op: 'list', path: '' },
    { op: 'list', path: '.aihub/share' },
  ]);
  await list.getByRole('button', { name: /login\.png/ }).click();
  await expect(page.getByRole('img', { name: 'login.png' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Скачать' })).toHaveAttribute('download', 'login.png');
  await page.getByRole('button', { name: 'Папка проекта' }).click();
  await expect(list.getByRole('button', { name: /^src\// })).toBeVisible();
});

test('файлы сессии: путь из сообщения агента открывает файл рядом с его папкой', async ({ page }) => {
  const session = {
    id: 'session-files',
    project_id: 'demo',
    worker_id: 'worker-a',
    engine: 'codex',
    provider: 'openai',
    model: 'gpt',
    status: 'completed',
    title: 'Executor',
    workdir: '/srv/demo/.aihub/worktrees/x',
    created_at: '2026-11-04T10:00:00Z',
    updated_at: '2026-11-04T10:05:00Z',
  };
  const asked: { op: string; path: string }[] = [];
  const answers = new Map<string, unknown>();
  await page.route('**/api/v0/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v0', '');
    const json = (value: unknown) => route.fulfill({ json: value });
    if (path === '/auth/login' || path === '/auth/refresh') return json({ access_token: 'fixture' });
    if (path === '/auth/me') return json({ id: 'u1', username: 'admin', role: 'admin' });
    if (path === '/events/stream-ticket') return json({ ticket: 'fixture' });
    if (path === '/projects') return json([{ id: 'demo', name: 'Demo', visibility: 'shared', allowed_paths: [] }]);
    if (path === '/sessions') return json([session]);
    if (path === `/sessions/${session.id}`) return json(session);
    if (path === `/sessions/${session.id}/files`) {
      const body = route.request().postDataJSON() as { op: string; path: string };
      asked.push(body);
      const id = `r${asked.length}`;
      const file = '.aihub/share/screens/login.png';
      answers.set(
        id,
        body.op === 'read' && body.path === file
          ? { status: 'completed', result: { path: file, size: 68, mime: 'image/png', updated_at: '', base64: PNG } }
          : body.op === 'list' && body.path === file
            ? { status: 'failed', error: 'папки нет' }
            : {
                status: 'completed',
                result: {
                  path: body.path,
                  share: null,
                  entries:
                    body.path === '.aihub/share/screens'
                      ? [{ name: 'login.png', path: file, dir: false, size: 68, updated_at: '' }]
                      : [],
                },
              },
      );
      return json({ request_id: id });
    }
    if (path.startsWith('/files/requests/')) return json(answers.get(path.split('/').pop() ?? ''));
    return json([]);
  });
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill('fixture');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.goto(`/workspace?project=demo&session=${session.id}`);
  await page.getByRole('tab', { name: 'Файлы' }).click();
  await page.getByLabel('Открыть путь').fill('./.aihub/share/screens/login.png');
  await page.getByRole('button', { name: 'Открыть', exact: true }).click();
  await expect(page.getByRole('img', { name: 'login.png' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Файлы' }).getByRole('button', { name: /login\.png/ })).toBeVisible();
});
