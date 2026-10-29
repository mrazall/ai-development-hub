import { expect, test, type Page, type Route } from '@playwright/test';

const worker = {
  id: 'worker-e2e',
  host: 'desktop-e2e',
  kind: 'local',
  status: 'online',
  labels: [],
  last_heartbeat_at: '2026-10-28T10:00:00Z',
  lease_ttl_s: 60,
};

const claude = {
  id: 'claude-1',
  name: 'Claude 1',
  kind: 'claude_code_subscription',
  worker_id: worker.id,
  models: ['claude-sonnet'],
  status: 'connected',
  status_detail: null,
  checked_at: '2026-10-28T10:00:00Z',
  identity: 'alice@example.com',
  duplicate_of: [],
};

const codex = {
  id: 'codex-1',
  name: 'Codex 1',
  kind: 'codex_subscription',
  worker_id: worker.id,
  models: ['gpt-5.6-luna'],
  status: 'connected',
  status_detail: null,
  checked_at: '2026-10-28T10:00:00Z',
  identity: null,
  duplicate_of: [],
};

const project = { id: 'e2e-project', name: 'E2E project', visibility: 'private' };
const session = {
  id: 'session-limit',
  task_id: null,
  project_id: project.id,
  worker_id: worker.id,
  engine: 'claude_code',
  provider: 'anthropic',
  model: 'claude-sonnet',
  auth_mode: 'subscription',
  workdir: '/tmp/e2e',
  branch: null,
  status: 'failed',
  status_source: 'native',
  external_ref: 'claude-session-ref',
  created_at: '2026-10-28T09:00:00Z',
  updated_at: '2026-10-28T10:00:00Z',
  resume_at: '2026-10-28T11:00:00Z',
  account_profile_id: claude.id,
  title: 'Сессия с лимитом',
};

type FixtureOptions = {
  accounts?: unknown[];
  foundLogins?: unknown[];
  alternatives?: unknown[];
  events?: unknown[];
  deleteStatus?: number;
  role?: 'admin' | 'viewer';
};
type JsonObject = Record<string, unknown>;
type PostedRequest = { method: string; path: string; body: JsonObject };

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function mockApi(page: Page, options: FixtureOptions = {}): Promise<{ posts: PostedRequest[] }> {
  const state = {
    accounts: options.accounts ?? [claude, codex],
    foundLogins: options.foundLogins ?? [],
    alternatives: options.alternatives ?? [],
    events: options.events ?? [],
  };
  const posts: PostedRequest[] = [];
  await page.route('**/api/v0/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v0', '');
    const method = request.method();
    const body = (request.postDataJSON?.() ?? {}) as JsonObject;
    if (method !== 'GET' && method !== 'DELETE') posts.push({ method, path, body });

    if (path === '/auth/login' && method === 'POST') return json(route, { access_token: 'e2e-token' });
    if (path === '/auth/me') return json(route, { id: 'user', username: 'user', role: options.role ?? 'admin' });
    if (path === '/accounts' && method === 'GET') return json(route, state.accounts);
    if (path === '/accounts/found-logins') return json(route, state.foundLogins);
    if (path === '/workers') return json(route, [worker]);
    if (path === '/workers/worker-e2e') return json(route, worker);
    if (path === '/accounts/next-id') return json(route, { id: 'claude-2', name: 'Claude 2' });
    if (path === '/accounts' && method === 'POST') {
      const created = { ...claude, id: body.id ?? 'claude-2', name: body.name ?? 'Claude 2' };
      state.accounts = [...state.accounts, created];
      return json(route, created, 201);
    }
    if (path === '/accounts/claude-1/login-command') {
      return json(route, {
        engine: 'claude',
        shell: 'CLAUDE_CONFIG_DIR=~/.aihub/accounts/claude-1/claude claude auth login',
        argv: ['claude', 'auth', 'login'],
        env: { CLAUDE_CONFIG_DIR: '~/.aihub/accounts/claude-1/claude' },
        worker_id: worker.id,
      });
    }
    if (path === '/accounts/claude-1/login-started' && method === 'POST')
      return json(route, { until: '2026-10-28T11:00:00Z' }, 202);
    if (path === '/accounts/claude-1/login-instructions' && method === 'POST')
      return json(route, { steps: [{ text: 'Run the official Claude login command.' }] });
    if (path === '/accounts/claude-1' && method === 'GET') return json(route, claude);
    if (path === '/accounts/claude-1' && method === 'DELETE') {
      return json(route, { detail: 'account has active sessions' }, options.deleteStatus ?? 204);
    }
    if (path === '/accounts/claude-1/alternative-accounts') return json(route, state.alternatives);
    if (path === '/sessions/session-limit') return json(route, session);
    if (path === '/sessions/session-limit/alternative-accounts') return json(route, state.alternatives);
    if (path === '/sessions/session-limit/continue-on-account' && method === 'POST')
      return json(route, { ...session, account_profile_id: body.account_profile_id, resume_at: null });
    if (path === '/projects') return json(route, [project]);
    if (path.startsWith('/projects/') && path.endsWith('/tasks')) return json(route, []);
    if (path === '/dashboard')
      return json(route, {
        projects: 1,
        tasks: {},
        workers: { online: 1, offline: 0 },
        sessions: { running: 0 },
        events: [],
        services: { api: 'ok', database: 'ok', knowledge: 'unknown' },
      });
    if (path === '/limits') return json(route, []);
    if (path === '/approvals' || path === '/notifications') return json(route, []);
    if (path === '/knowledge/health') return json(route, { status: 'ok' });
    if (path === '/sessions') {
      // The workspace asks for both the selected project's sessions and the all-projects list.
      return json(route, [session]);
    }
    if (path === '/events' || path.startsWith('/events?')) return json(route, state.events);
    if (path.startsWith('/sessions/') && path.endsWith('/attachments')) return json(route, []);
    if (path === '/events/stream-ticket' && method === 'POST') return json(route, { ticket: 'e2e-ticket' });
    if (path === '/system/info') return json(route, { demo: false });
    if (path.startsWith('/terminal/')) return json(route, {});
    return json(route, {});
  });
  await page.route('**/api/v0/events/stream**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: session.status\ndata: ${JSON.stringify({
        cursor: 8,
        session_id: session.id,
        kind: 'session.status',
        source: 'control-plane',
        ts: session.updated_at,
        payload: { status: session.status },
        redacted: false,
      })}\n\n`,
    }),
  );
  return { posts };
}

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill('mocked');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

test('создаёт Claude с next-id и принимает найденный вход', async ({ page }) => {
  const { posts } = await mockApi(page, {
    accounts: [],
    foundLogins: [{ worker_id: worker.id, engine: 'claude', identity: 'found@example.com', kind: claude.kind }],
  });
  await login(page);
  await page.goto('/settings/accounts');
  await page.getByRole('button', { name: '+ Добавить Claude' }).click();
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page.getByLabel('ID профиля')).toHaveValue('claude-2');
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect
    .poll(() => posts.find((item) => item.path === '/accounts' && item.body.id === 'claude-2')?.body)
    .toMatchObject({
      id: 'claude-2',
      kind: claude.kind,
      worker_id: worker.id,
    });

  await expect(page.getByRole('heading', { name: 'Найденные входы' })).toBeVisible();
  await page.getByRole('button', { name: /Использовать вход Claude/ }).click();
  await expect
    .poll(() => posts.find((item) => item.path === '/accounts' && item.body.adopt_found_login)?.body)
    .toMatchObject({
      kind: claude.kind,
      worker_id: worker.id,
      adopt_found_login: true,
    });
});

test('показывает identity, duplicate warning, login terminal и ошибку удаления 409', async ({ page }) => {
  const duplicate = { ...claude, duplicate_of: ['claude-existing'] };
  const { posts } = await mockApi(page, { accounts: [duplicate], deleteStatus: 409 });
  await login(page);
  await page.goto('/settings/accounts');
  await expect(page.getByText('alice@example.com')).toBeVisible();
  await expect(page.getByText(/уже подключён в профиле claude-existing/)).toBeVisible();
  await page.getByRole('button', { name: 'Действия: Claude 1', exact: true }).click();
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.locator('.login-terminal')).toBeVisible();
  await expect.poll(() => posts.some((item) => item.path === '/accounts/claude-1/login-started')).toBeTruthy();
  page.once('dialog', (dialog) => void dialog.accept());
  await page.getByRole('button', { name: 'Удалить' }).click();
  await expect(page.getByText('Профиль нельзя удалить: у него есть активные сессии.')).toBeVisible();
});

test('viewer cannot open the embedded login terminal and gets the fallback instructions', async ({ page }) => {
  const { posts } = await mockApi(page, { role: 'viewer' });
  await login(page);
  await page.goto('/settings/accounts');
  await page.getByRole('button', { name: 'Действия: Claude 1', exact: true }).click();
  await expect(page.getByText('Встроенный терминал доступен только администраторам.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Войти' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Запасной путь: инструкция входа' }).click();
  await expect(page.getByText('Run the official Claude login command.')).toBeVisible();
  await expect.poll(() => posts.some((item) => item.path === '/accounts/claude-1/login-instructions')).toBeTruthy();
  expect(posts.some((item) => item.path === '/accounts/claude-1/login-command')).toBeFalsy();
});

test('переключает сессию на альтернативный аккаунт с лимитами и summary mode', async ({ page }) => {
  const switched = {
    ...codex,
    id: 'claude-2',
    name: 'Claude 2',
    kind: claude.kind,
    worker_id: worker.id,
    models: ['claude-sonnet'],
  };
  const { posts } = await mockApi(page, {
    alternatives: [
      {
        account: switched,
        limits: {
          id: switched.id,
          name: switched.name,
          windows: [{ kind: 'five_hour', used_percent: 35, resets_at: null }],
        },
        resume_mode: 'summary',
      },
    ],
    events: [
      {
        cursor: 7,
        session_id: session.id,
        kind: 'session.account_switched',
        source: 'control-plane',
        ts: '2026-10-28T10:05:00Z',
        payload: { from: claude.id, to: switched.id, resume_mode: 'summary' },
      },
    ],
  });
  await login(page);
  await page.goto(`/workspace?project=${project.id}&session=${session.id}`);
  await expect(page.getByRole('button', { name: 'Продолжить сейчас на другом аккаунте' })).toBeVisible();
  await page.getByRole('button', { name: 'Продолжить сейчас на другом аккаунте' }).click();
  const alternativesDialog = page.getByRole('dialog', { name: 'Продолжить на другом аккаунте' });
  await expect(alternativesDialog.getByText('Claude 2', { exact: true })).toBeVisible();
  await expect(alternativesDialog.getByText('Беседа начнётся заново с краткой сводкой', { exact: true })).toBeVisible();
  await expect(
    alternativesDialog.getByText('0k вход (0k из кэша) · 0k выход · Claude 2 · лимит 5 ч: 35%', { exact: true }),
  ).toBeVisible();
  await alternativesDialog
    .getByRole('button', { name: 'Продолжить — беседа начнётся заново с краткой сводкой', exact: true })
    .click();
  await expect
    .poll(
      () =>
        posts.find((item) => item.method === 'POST' && item.path === '/sessions/session-limit/continue-on-account')
          ?.body,
    )
    .toMatchObject({ account_profile_id: switched.id });

  await page.getByRole('tab', { name: 'События' }).click();
  await expect(
    page.getByText('Сессия продолжена на аккаунте claude-2; беседа началась заново с краткой сводкой.', {
      exact: true,
    }),
  ).toBeVisible();
});
