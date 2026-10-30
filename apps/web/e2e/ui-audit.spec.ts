import { expect, test, type Page, type TestInfo } from '@playwright/test';
import path from 'node:path';
import { inspectGeometry, type GeometryReport } from './fixtures/geometry';

export type RouteContract = {
  id: string;
  path: string;
  layout: 'standard' | 'workspace' | 'split-view' | 'table' | 'graph' | 'chat' | 'terminal';
  scrollOwner: 'document' | 'content' | 'panel' | 'list' | 'terminal' | 'dialog';
  allowDocumentYScroll: boolean;
  allowDocumentXScroll: boolean;
  states: string[];
  critical?: boolean;
};

// Source of truth: the Routes tree in src/main.tsx. Dynamic paths use stable fixture IDs.
export const ROUTE_CONTRACTS: RouteContract[] = [
  {
    id: 'dashboard',
    path: '/',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'workspace',
    path: '/workspace',
    layout: 'workspace',
    scrollOwner: 'panel',
    allowDocumentYScroll: false,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'chats',
    path: '/chats',
    layout: 'chat',
    scrollOwner: 'list',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'chat-detail',
    path: '/chats/chat-fixture',
    layout: 'chat',
    scrollOwner: 'panel',
    allowDocumentYScroll: false,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'agents',
    path: '/agents',
    layout: 'graph',
    scrollOwner: 'panel',
    allowDocumentYScroll: false,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'projects',
    path: '/projects',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'project-detail',
    path: '/projects/project-fixture',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
  },
  {
    id: 'tasks',
    path: '/tasks',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'workers',
    path: '/workers',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'sessions',
    path: '/sessions',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'session-detail',
    path: '/sessions/session-fixture',
    layout: 'split-view',
    scrollOwner: 'panel',
    allowDocumentYScroll: false,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
  },
  {
    id: 'session-files',
    path: '/sessions/session-fixture/files',
    layout: 'split-view',
    scrollOwner: 'panel',
    allowDocumentYScroll: false,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'notifications',
    path: '/notifications',
    layout: 'table',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['empty', 'populated', 'error'],
  },
  {
    id: 'knowledge',
    path: '/knowledge',
    layout: 'graph',
    scrollOwner: 'panel',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'knowledge-drafts',
    path: '/knowledge/drafts',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['empty', 'populated', 'error'],
  },
  {
    id: 'backups',
    path: '/backups',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'health',
    path: '/health',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
  },
  {
    id: 'limits',
    path: '/limits',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'settings',
    path: '/settings',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'settings-accounts',
    path: '/settings/accounts',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
    critical: true,
  },
  {
    id: 'settings-mcp',
    path: '/settings/mcp',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'settings-projects',
    path: '/settings/projects',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'settings-workers',
    path: '/settings/workers',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'settings-sessions',
    path: '/settings/sessions',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'settings-users',
    path: '/settings/users',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'populated', 'error'],
  },
  {
    id: 'settings-system',
    path: '/settings/system',
    layout: 'table',
    scrollOwner: 'content',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['loading', 'empty', 'populated', 'error'],
  },
  {
    id: 'login',
    path: '/login',
    layout: 'standard',
    scrollOwner: 'document',
    allowDocumentYScroll: true,
    allowDocumentXScroll: false,
    states: ['empty', 'error'],
    critical: true,
  },
];

const project = {
  id: 'project-fixture',
  name: 'Geometry Fixture',
  visibility: 'private',
  repo_url: null,
  allowed_paths: [],
  allowed_commands: [],
};
const session = {
  id: 'session-fixture',
  task_id: null,
  project_id: 'project-fixture',
  worker_id: 'worker-fixture',
  permission_mode: 'default',
  engine: 'mock',
  provider: 'local',
  model: 'fixture',
  auth_mode: 'none',
  workdir: '/tmp/fixture',
  branch: null,
  status: 'completed',
  status_source: 'native',
  external_ref: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  title: 'Geometry fixture',
  role: 'orchestrator',
};
const worker = {
  id: 'worker-fixture',
  host: 'fixture',
  kind: 'local',
  status: 'offline',
  labels: [],
  last_heartbeat_at: null,
  lease_ttl_s: 60,
};

export async function installAuditMocks(page: Page): Promise<void> {
  await page.route('**/api/v0/events/stream**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': mock stream\n\n' }),
  );
  await page.route('**/api/v0/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v0', '');
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/login' || path === '/auth/refresh') return json({ access_token: 'ui-audit-fixture-token' });
    if (path === '/auth/me') return json({ id: 'user-fixture', username: 'ui-audit', role: 'admin' });
    if (path === '/dashboard')
      return json({
        projects: 1,
        tasks: {},
        workers: {},
        sessions: {},
        events: [],
        services: { api: 'ok', database: 'ok', knowledge: 'ok' },
      });
    if (path === '/system/info') return json({ demo: false, obsidian_vault: '' });
    if (path === '/health' || path === '/system/health')
      return json({
        api: 'ok',
        database: 'ok',
        knowledge: 'ok',
        workers: 'ok',
        limits: 'ok',
        backups: 'ok',
        errors: [],
      });
    if (path === '/projects' || path.startsWith('/projects?')) return json([project]);
    if (path === '/projects/project-fixture') return json(project);
    if (path.endsWith('/tasks')) return json([]);
    if (path === '/workers' || path.startsWith('/workers?')) return json([worker]);
    if (path === '/workers/worker-fixture') return json(worker);
    if (path === '/sessions' || path.startsWith('/sessions?')) return json([session]);
    if (path === '/sessions/session-fixture') return json(session);
    if (path === '/events') return json([]);
    if (path === '/events/stream-ticket') return json({ ticket: 'ui-audit-fixture-ticket' });
    if (path.includes('/sessions/session-fixture/files')) return json({ path: '', entries: [] });
    if (path.includes('/sessions/session-fixture/git/'))
      return json(path.endsWith('/status') ? { branch: null, clean: true, files: [] } : []);
    if (path === '/graph' || path.startsWith('/graph?')) return json({ nodes: [], edges: [] });
    if (
      path === '/accounts' ||
      path.startsWith('/accounts?') ||
      path === '/accounts/found-logins' ||
      path === '/accounts/next-id'
    )
      return json([]);
    if (path === '/mcp' || path === '/mcp/config') return json([]);
    if (path === '/limits') return json([]);
    if (
      path === '/notifications' ||
      path.startsWith('/notifications?') ||
      path === '/approvals' ||
      path.startsWith('/approvals?')
    )
      return json([]);
    if (path === '/chats' || path.startsWith('/chats?')) return json([]);
    if (path === '/chats/chat-fixture')
      return json({
        id: 'chat-fixture',
        title: 'Fixture chat',
        pinned: false,
        updated_at: '2026-01-01T00:00:00Z',
        messages: [],
      });
    if (path === '/knowledge/graph') return json({ nodes: [], edges: [] });
    if (path.startsWith('/knowledge/documents'))
      return json(
        path.includes('/documents/')
          ? { id: 'doc-fixture', title: 'Fixture', content: '' }
          : { items: [], total: 0, offset: 0, limit: 50 },
      );
    if (path.startsWith('/knowledge/search')) return json({ hits: [] });
    if (path.startsWith('/knowledge/drafts')) return json({ drafts: [] });
    if (path === '/backups' || path === '/backups/status') return json([]);
    if (path === '/system/settings' || path === '/users') return json([]);
    return json({}, request.method() === 'POST' ? 201 : 200);
  });
}

test.describe('regressions', () => {
  test('shell keeps navigation and content geometry reachable', async ({ page }, testInfo) => {
    await installAuditMocks(page);
    await authenticate(page);
    await page.goto('/');
    await disableMotion(page);
    await waitForLayout(page);

    const report = await inspectGeometry(page, { allowDocumentYScroll: true, allowDocumentXScroll: false });
    const shellFindings = report.findings.filter((finding) =>
      finding.selectors.some((value) =>
        /^(html|body|div\.app-shell|main\.content|nav\.nav|button\.nav-more)$/.test(value),
      ),
    );
    expect(shellFindings, `shell geometry must not hide or obstruct its controls (${testInfo.project.name})`).toEqual(
      [],
    );
  });
});

async function authenticate(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel(/Пользователь|User|Username/i).fill('ui-audit');
  await page.getByLabel(/Пароль|Password/i).fill('fixture-password');
  await page.getByRole('button', { name: /Войти|Sign in|Log in/i }).click();
  await expect(page.getByRole('navigation', { name: /Основная навигация|Main navigation/i })).toBeVisible();
}

async function waitForLayout(page: Page): Promise<void> {
  // Do not wait for networkidle: the application owns an event-stream connection.
  const root = page.locator('main.content, main.auth').first();
  await expect(root, 'route did not render an application root (main.content or main.auth)').toBeVisible({
    timeout: 15_000,
  });
  await page.waitForFunction(
    () => {
      const layout = document.querySelector('main.content, main.auth');
      if (!layout) return false;
      const rect = layout.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    },
    undefined,
    { timeout: 15_000 },
  );
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  );
}

async function disableMotion(page: Page): Promise<void> {
  await page.addStyleTag({
    content:
      '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
  });
}

async function auditState(
  page: Page,
  route: RouteContract,
  testInfo: TestInfo,
  label: string,
): Promise<GeometryReport> {
  await waitForLayout(page);
  const report = await inspectGeometry(page, { ...route, scenario: label });
  const safe = `${route.id}-${label}-${testInfo.project.name}`;
  const shot = path.join(testInfo.outputDir, `${safe}.png`);
  await page.screenshot({ path: shot, fullPage: true });
  await testInfo.attach(`${safe}-screenshot`, { path: shot, contentType: 'image/png' });
  if (report.findings.length) {
    await testInfo.attach(`${safe}-findings`, {
      body: JSON.stringify(report.findings, null, 2),
      contentType: 'application/json',
    });
  }
  return report;
}

async function runCriticalDynamics(page: Page, route: RouteContract, testInfo: TestInfo): Promise<GeometryReport[]> {
  if (!route.critical) return [];
  const reports: GeometryReport[] = [];
  const mobileToggle = page.getByRole('button', { name: /Меню|Menu/i });
  if (await mobileToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
    await mobileToggle.click();
    await expect(page.locator('#mobile-navigation')).toBeVisible();
    reports.push(await auditState(page, route, testInfo, 'mobile-navigation-open'));
    await page.getByRole('button', { name: /Закрыть меню|Close menu/i }).click();
  }
  const more = page.getByRole('button', { name: /Ещё|More/i });
  if (await more.isVisible({ timeout: 1000 }).catch(() => false)) {
    await more.click();
    await expect(page.locator('.nav-menu')).toBeVisible();
    reports.push(await auditState(page, route, testInfo, 'settings-menu-open'));
    await more.click();
  }
  const dialogTrigger = page.getByRole('button', { name: /Создать проект|Create project/i });
  if (await dialogTrigger.isVisible({ timeout: 1000 }).catch(() => false)) {
    await dialogTrigger.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    reports.push(await auditState(page, route, testInfo, 'dialog-open'));
    await page
      .getByRole('dialog')
      .getByRole('button', { name: /Отмена|Cancel/i })
      .click();
  }
  const tabs = page.getByRole('tab');
  if (
    await tabs
      .nth(1)
      .isVisible({ timeout: 1000 })
      .catch(() => false)
  ) {
    await tabs.nth(1).click();
    reports.push(await auditState(page, route, testInfo, 'tab-switched'));
  }
  return reports;
}

for (const route of ROUTE_CONTRACTS) {
  test(`geometry audit: ${route.id} (${route.path})`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await installAuditMocks(page);
    if (testInfo.project.name.includes('font-20')) {
      await page.addInitScript(() => {
        const style = document.createElement('style');
        style.textContent = 'html { font-size: 20px !important; }';
        document.documentElement.append(style);
      });
    }
    if (route.id === 'login') await page.goto(route.path);
    else {
      await authenticate(page);
      await page.goto(route.path);
    }
    await disableMotion(page);
    const report = await auditState(page, route, testInfo, 'base');
    const dynamicReports = await runCriticalDynamics(page, route, testInfo);
    const allFindings = [report, ...dynamicReports].flatMap((item) => item.findings);
    const details = allFindings.map((finding) => ({ route: route.path, viewport: report.viewport, ...finding }));
    expect
      .soft(
        allFindings,
        `${route.path} @ ${report.viewport.width}x${report.viewport.height}: ${JSON.stringify(details)}`,
      )
      .toEqual([]);
    expect(allFindings, `Final geometry assertion for ${route.path}: ${JSON.stringify(details)}`).toEqual([]);
    await testInfo.attach('geometry-report.json', {
      body: JSON.stringify({ route, reports: [report, ...dynamicReports] }, null, 2),
      contentType: 'application/json',
    });
  });
}
