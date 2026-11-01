import { expect, test, type Page } from '@playwright/test';

// The worker is played by fixtures: each POST …/instructions answers through GET /instructions/requests/{id}.
const AGENTS = 'Правила проекта\nИсполнители: Codex\nКонец\n';
const SHA = 'a'.repeat(64);

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

function fakeWorker(
  page: Page,
  onWrite: (body: Record<string, unknown>) => { result?: unknown; error?: string; code?: number },
) {
  const answers = new Map<string, unknown>();
  let next = 0;
  return page.route(
    /\/api\/v0\/(projects|workers)\/[^/]+\/instructions$|\/api\/v0\/instructions\/requests\//,
    async (route) => {
      const url = route.request().url();
      if (url.includes('/instructions/requests/')) {
        const id = url.split('/').pop() as string;
        return route.fulfill({ json: answers.get(id) });
      }
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const id = `r${(next += 1)}`;
      const shared = url.includes('/workers/');
      if (body.op === 'list') {
        answers.set(id, {
          status: 'completed',
          result: shared
            ? {
                git: false,
                files: [
                  {
                    path: 'claude/CLAUDE.md',
                    readers: ['claude'],
                    exists: true,
                    size: 10,
                    sha256: SHA,
                    updated_at: null,
                    skill: null,
                    accounts: ['claude-main', 'claude-second'],
                  },
                ],
              }
            : {
                git: true,
                files: [
                  {
                    path: 'AGENTS.md',
                    readers: ['codex'],
                    exists: true,
                    size: AGENTS.length,
                    sha256: SHA,
                    updated_at: null,
                    skill: null,
                  },
                  {
                    path: 'CLAUDE.md',
                    readers: ['claude'],
                    exists: false,
                    size: null,
                    sha256: null,
                    updated_at: null,
                    skill: null,
                  },
                ],
              },
        });
      } else if (body.op === 'read') {
        answers.set(id, {
          status: 'completed',
          result: {
            path: body.path,
            readers: ['codex'],
            exists: true,
            size: AGENTS.length,
            sha256: SHA,
            updated_at: null,
            skill: null,
            content: AGENTS,
            accounts: ['claude-main', 'claude-second'],
          },
        });
      } else {
        const answer = onWrite(body);
        answers.set(
          id,
          answer.error
            ? { status: 'failed', error: answer.error, code: answer.code }
            : { status: 'completed', result: answer.result },
        );
      }
      return route.fulfill({ json: { request_id: id, worker_id: 'worker-b' } });
    },
  );
}

test('инструкции: правка показывает ровно изменённую строку и уходит с версией файла', async ({ page }) => {
  const writes: Record<string, unknown>[] = [];
  await fakeWorker(page, (body) => {
    writes.push(body);
    return { result: { commit: 'abc1234', backup: null, snapshot: null, sha256: 'b'.repeat(64) } };
  });
  await signIn(page);
  await page.goto('/projects/demo/instructions');
  await page.getByRole('button', { name: /AGENTS\.md/ }).click();
  const editor = page.getByLabel('Текст файла');
  await expect(editor).toHaveValue(AGENTS);
  await expect(page.getByText('Читает: Codex · действует на все сессии проекта')).toBeVisible();
  await editor.fill(AGENTS.replace('Исполнители: Codex', 'Исполнители: Codex Terra'));
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Сохранить AGENTS.md?' });
  await expect(dialog.locator('.is-removed')).toHaveText(['- Исполнители: Codex']);
  await expect(dialog.locator('.is-added')).toHaveText(['+ Исполнители: Codex Terra']);
  await expect(dialog.getByText('Будет коммит только этого файла')).toBeVisible();
  await dialog.getByRole('button', { name: 'Сохранить' }).click();
  await expect(page.getByText('Сохранено · коммит abc1234')).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ op: 'write', path: 'AGENTS.md', base_sha256: SHA });
  expect(String(writes[0].content)).toContain('Codex Terra');
});

test('инструкции: конфликт версий объясняется и предлагает загрузить файл заново', async ({ page }) => {
  await fakeWorker(page, () => ({ error: 'файл изменился на воркере', code: 409 }));
  await signIn(page);
  await page.goto('/projects/demo/instructions');
  await page.getByRole('button', { name: /AGENTS\.md/ }).click();
  await page.getByLabel('Текст файла').fill('другое\n');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить' }).click();
  await expect(page.getByRole('alert')).toContainText('файл изменился на воркере');
  await expect(page.getByRole('button', { name: 'Загрузить версию с воркера' })).toBeVisible();
});

test('инструкции: навык с неверным именем не создать; общий файл называет аккаунты', async ({ page }) => {
  await page.route('**/api/v0/accounts', (route) =>
    route.fulfill({
      json: [
        { id: 'claude-main', name: 'Claude основной' },
        { id: 'claude-second', name: 'Claude второй' },
      ],
    }),
  );
  await fakeWorker(page, () => ({ result: {} }));
  await signIn(page);
  await page.goto('/projects/demo/instructions');
  await page.getByRole('button', { name: '+ Новый навык' }).click();
  const name = page.getByLabel('Имя');
  await name.fill('Bad_Name');
  await expect(name).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('button', { name: 'Создать' })).toBeDisabled();
  await name.fill('release-notes');
  await expect(page.getByRole('button', { name: 'Создать' })).toBeEnabled();
  await page.getByRole('button', { name: 'Создать' }).click();
  await expect(page.getByLabel('Текст файла')).toHaveValue(/name: release-notes/);

  await page.goto('/settings/workers/worker-b/instructions');
  await expect(page.getByRole('heading', { name: 'Общие для воркера' })).toBeVisible();
  await page.getByRole('button', { name: /CLAUDE\.md/ }).click();
  await expect(page.getByText('действует на аккаунты: Claude основной, Claude второй')).toBeVisible();
});
