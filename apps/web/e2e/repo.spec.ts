// UI contract: repo-graph (SVG), repo-commit (circle, data-sha), repo-ref
// (inside its commit, or carrying data-sha), repo-pr-row (data-number),
// repo-pr-checks, repo-pr-merge, repo-pr-close, repo-run-row (data-id),
// repo-run-toggle, repo-run-job, repo-run-rerun. See docs/repo/testids.md.
import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const fixture = (name: string) =>
  JSON.parse(readFileSync(fileURLToPath(new URL(`./fixtures/repo/${name}.json`, import.meta.url)), 'utf8'));
const graph = fixture('graph');
const github = fixture('github');
const commit = fixture('commit');
const project = 'project-fixture';
const api = `**/api/v0/projects/${project}/repo`;

async function openRepo(page: Page, unavailable = false) {
  await page.route('**/api/v0/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v0', '');
    if (path === '/auth/login' || path === '/auth/refresh')
      return route.fulfill({ json: { access_token: 'fixture-token' } });
    if (path === '/auth/me') return route.fulfill({ json: { id: 'user-fixture', username: 'admin', role: 'admin' } });
    if (path === `/projects/${project}`)
      return route.fulfill({
        json: {
          id: project,
          name: 'Repo fixture',
          visibility: 'private',
          repo_url: null,
          allowed_paths: [],
          allowed_commands: [],
        },
      });
    if (path === '/events/stream-ticket') return route.fulfill({ json: { ticket: 'fixture-ticket' } });
    return route.fulfill({ json: [] });
  });
  await page.route(`${api}/graph**`, (route) => route.fulfill({ json: graph }));
  await page.route(`${api}/github**`, (route) =>
    route.fulfill({
      json: unavailable
        ? {
            ...github,
            available: false,
            reason: 'gh is not logged in on worker fixture — run: gh auth login',
            pulls: [],
            runs: [],
          }
        : github,
    }),
  );
  await page.route(`${api}/commits/**`, (route) => route.fulfill({ json: commit }));
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill('fixture');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.goto(`/projects/${project}/repo`);
  await expect(page.getByTestId('repo-graph')).toBeVisible();
}

test('graph, pull requests and CI show fixture content and confirm actions', async ({ page }) => {
  const actions: unknown[] = [];
  await openRepo(page);
  await page.route(`${api}/actions`, async (route) => {
    actions.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: { request_id: 'request-fixture' } });
  });
  const graphView = page.getByTestId('repo-graph');
  await expect(graphView.locator('circle[data-testid="repo-commit"]')).toHaveCount(12);
  const merge = graph.commits[0];
  for (const parent of merge.parents) {
    await expect(
      graphView.locator(`[data-testid="repo-edge"][data-from="${merge.sha}"][data-to="${parent}"]`),
    ).toHaveCount(1);
  }
  const mainRef = graphView.getByTestId('repo-ref').filter({ hasText: /^main$/ });
  await expect(mainRef).toHaveAttribute('data-sha', graph.commits[0].sha);
  await expect(graphView.getByRole('link', { name: 'Fix login' })).toHaveAttribute('href', '/sessions/session-fixture');

  const pr12 = page.locator('[data-testid="repo-pr-row"][data-number="12"]');
  const pr14 = page.locator('[data-testid="repo-pr-row"][data-number="14"]');
  await expect(pr12.getByTestId('repo-pr-checks')).toContainText(/3\s*✓\s*·\s*1\s*✗/);
  const blockedMerge = pr12.getByTestId('repo-pr-merge');
  const checksBox = await pr12.getByTestId('repo-pr-checks').boundingBox();
  const mergeBox = await blockedMerge.boundingBox();
  expect(checksBox).not.toBeNull();
  expect(mergeBox).not.toBeNull();
  expect(checksBox!.y).toBeLessThan(mergeBox!.y + mergeBox!.height);
  expect(mergeBox!.y).toBeLessThan(checksBox!.y + checksBox!.height);
  await expect(blockedMerge).toBeDisabled();
  await expect(blockedMerge).toHaveAttribute('title', /\S+/);
  await expect(pr14.getByTestId('repo-pr-merge')).toBeEnabled();
  await pr14.getByTestId('repo-pr-merge').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('#14');
  await expect(dialog).toContainText('Improve dashboard');
  await dialog.getByRole('button', { name: /отмена|cancel/i }).click();
  await expect(dialog).toBeHidden();
  expect(actions).toEqual([]);
  await pr14.getByTestId('repo-pr-merge').click();
  const request = page.waitForRequest(
    (req) => req.url().endsWith(`/projects/${project}/repo/actions`) && req.method() === 'POST',
  );
  await dialog.getByRole('button', { name: /слить|merge/i }).click();
  expect((await request).postDataJSON()).toEqual({ action: 'merge_pr', target: '14', confirm: true });
  await expect.poll(() => actions).toEqual([{ action: 'merge_pr', target: '14', confirm: true }]);

  const failed = page.locator('[data-testid="repo-run-row"][data-id="101"]');
  for (const meta of await page.locator('.repo-run-meta').all()) {
    expect(await meta.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await failed.getByTestId('repo-run-toggle').click();
  const jobs = failed.getByTestId('repo-run-job');
  await expect(jobs).toHaveCount(2);
  for (const [index, name, duration, url] of [
    [0, 'Tests', /1\s*(?:min|мин)\s*20\s*(?:s|с)/i, github.runs[2].jobs[0].url],
    [1, 'Lint', /45\s*(?:s|с)/i, github.runs[2].jobs[1].url],
  ] as const) {
    await expect(jobs.nth(index)).toContainText(name);
    await expect(jobs.nth(index)).toContainText(duration);
    await expect(jobs.nth(index).getByRole('link')).toHaveAttribute('href', url);
  }
  await expect(failed.getByTestId('repo-run-rerun')).toBeVisible();
  await expect(page.getByTestId('repo-run-rerun')).toHaveCount(1);
  await expect(page.locator('body')).not.toContainText(/\b(?:in_progress|failure)\b/);
});

test('unavailable GitHub explains the reason', async ({ page }) => {
  await openRepo(page, true);
  await expect(page.getByText('gh is not logged in on worker fixture — run: gh auth login')).toBeVisible();
});

test('layout fits mobile width and desktop height', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openRepo(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => innerWidth));
  for (const viewport of [
    { width: 1600, height: 900 },
    { width: 1920, height: 1080 },
    { width: 1366, height: 860 },
  ]) {
    await page.setViewportSize(viewport);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
  }
});
