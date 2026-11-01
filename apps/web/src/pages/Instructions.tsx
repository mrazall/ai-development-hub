import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { AccountProfile } from '../api/types';
import { arrayOrEmpty, useApi } from '../api/useApi';
import { MarkdownView } from '../components/MarkdownView';
import { ConfirmDialog, Dialog, ErrorBanner, Loading } from '../components/ui';
import { t } from '../i18n';

type Target = { kind: 'project' | 'worker'; id: string };
type FileEntry = {
  path: string;
  readers: string[];
  exists: boolean;
  size: number | null;
  sha256: string | null;
  updated_at: string | null;
  skill: string | null;
  accounts?: string[];
};
type Listing = { files: FileEntry[]; git: boolean };
type Opened = FileEntry & { content: string };
type Backup = { id: string; size: number; content: string };
type Failure = Error & { code?: number };

const MAX_BYTES = 256 * 1024;
const SKILL_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
const READER_LABELS: Record<string, string> = { claude: 'Claude Code', codex: 'Codex' };

/** Ask the worker through the hub and wait for its answer (the hub hands it back once). */
async function workerCall<T>(target: Target, body: Record<string, unknown>): Promise<T> {
  const base = target.kind === 'project' ? `/projects/${target.id}` : `/workers/${target.id}`;
  const queued = await api<{ request_id: string }>(`${base}/instructions`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  const started = Date.now();
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const answer = await api<{ status: string; result?: T; error?: string; code?: number }>(
      `/instructions/requests/${queued.request_id}`,
    );
    if (answer.status === 'completed') return answer.result as T;
    if (answer.status === 'failed') throw Object.assign(new Error(answer.error), { code: answer.code });
    if (Date.now() - started > 40_000) throw new Error(t('Воркер не ответил за 40 с — он занят или не в сети'));
  }
}

const errorMessage = (cause: unknown) =>
  cause instanceof ApiError || cause instanceof Error ? cause.message : String(cause);

function fileTitle(path: string): string {
  const parts = path.split('/');
  if (path.endsWith('/SKILL.md')) return parts[parts.length - 2];
  return parts[parts.length - 1];
}

/** Group of the file in the list: project, project skills, the worker's shared files, one account's own. */
function groupOf(target: Target, file: FileEntry): string {
  if (target.kind === 'project') return file.skill ? 'skills' : 'project';
  return file.path.startsWith('accounts/') ? `account:${file.path.split('/')[1]}` : 'shared';
}

/** Changed lines between two texts (prefix/suffix trimmed, then a bounded LCS). */
function lineDiff(before: string, after: string): { kind: ' ' | '+' | '-'; text: string }[] {
  const a = before.split('\n');
  const b = after.split('\n');
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1;
    endB -= 1;
  }
  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);
  const out: { kind: ' ' | '+' | '-'; text: string }[] = [];
  const context = (lines: string[]) => lines.forEach((text) => out.push({ kind: ' ', text }));
  context(a.slice(Math.max(0, start - 2), start));
  if (midA.length * midB.length > 4_000_000) {
    midA.forEach((text) => out.push({ kind: '-', text }));
    midB.forEach((text) => out.push({ kind: '+', text }));
  } else {
    const table = Array.from({ length: midA.length + 1 }, () => new Uint32Array(midB.length + 1));
    for (let i = midA.length - 1; i >= 0; i -= 1)
      for (let j = midB.length - 1; j >= 0; j -= 1)
        table[i][j] = midA[i] === midB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    let i = 0;
    let j = 0;
    while (i < midA.length || j < midB.length) {
      if (i < midA.length && j < midB.length && midA[i] === midB[j]) {
        out.push({ kind: ' ', text: midA[i] });
        i += 1;
        j += 1;
      } else if (j < midB.length && (i === midA.length || table[i][j + 1] >= table[i + 1][j])) {
        out.push({ kind: '+', text: midB[j] });
        j += 1;
      } else {
        out.push({ kind: '-', text: midA[i] });
        i += 1;
      }
    }
  }
  context(a.slice(endA, endA + 2));
  return out;
}

function Diff({ before, after }: { before: string; after: string }): JSX.Element {
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  const changed = lines.filter((line) => line.kind !== ' ').length;
  return (
    <div className="instructions-diff" aria-label={t('Изменения')}>
      {changed === 0 ? (
        <p className="muted">{t('Изменений нет.')}</p>
      ) : (
        <pre>
          {lines.map((line, index) => (
            <span key={index} className={line.kind === '+' ? 'is-added' : line.kind === '-' ? 'is-removed' : undefined}>
              {line.kind} {line.text}
              {'\n'}
            </span>
          ))}
        </pre>
      )}
    </div>
  );
}

function skillTemplate(name: string, description: string): string {
  return `---\nname: ${name}\ndescription: ${description || t('Когда применять этот навык')}\n---\n\n# ${name}\n\n${t('Что делать по шагам.')}\n`;
}

/** AGENTS.md, CLAUDE.md and skills that agents read: listed, read and edited on the worker. */
export function Instructions({ target }: { target: Target }): JSX.Element {
  const [listing, setListing] = useState<Listing | null>(null);
  const [listError, setListError] = useState('');
  const [opened, setOpened] = useState<Opened | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<{ message: string; conflict: boolean } | null>(null);
  const [notice, setNotice] = useState('');
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [review, setReview] = useState(false);
  const [newSkill, setNewSkill] = useState<{ name: string; description: string } | null>(null);
  const [removing, setRemoving] = useState(false);
  const [history, setHistory] = useState<Backup[] | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const accounts = useApi<AccountProfile[]>('/accounts');
  const accountName = (id: string) => arrayOrEmpty(accounts.data).find((item) => item.id === id)?.name ?? id;
  const dirty = opened !== null && text !== opened.content;
  const area = useRef<HTMLTextAreaElement>(null);
  const gutter = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setListError('');
    try {
      setListing(await workerCall<Listing>(target, { op: 'list' }));
    } catch (cause) {
      setListError(errorMessage(cause));
    }
  }, [target.kind, target.id]);
  useEffect(() => {
    void load();
  }, [load]);

  const open = async (path: string) => {
    setBusy('open');
    setError(null);
    setNotice('');
    try {
      const file = await workerCall<Opened>(target, { op: 'read', path });
      setOpened(file);
      setText(file.content);
      setMode('edit');
    } catch (cause) {
      setError({ message: errorMessage(cause), conflict: false });
    } finally {
      setBusy('');
    }
  };
  const choose = (path: string) => (dirty ? setPending(path) : void open(path));

  const save = async () => {
    if (!opened) return;
    setReview(false);
    setBusy('save');
    setError(null);
    try {
      const result = await workerCall<{ commit: string | null; backup: string | null; sha256: string }>(target, {
        op: 'write',
        path: opened.path,
        content: text,
        ...(opened.sha256 ? { base_sha256: opened.sha256 } : {}),
      });
      setOpened({ ...opened, content: text, sha256: result.sha256, exists: true });
      setNotice(
        result.commit
          ? t('Сохранено · коммит {0}', result.commit)
          : result.backup
            ? t('Сохранено · прошлая версия в истории')
            : t('Сохранено'),
      );
      void load();
    } catch (cause) {
      const failure = cause as Failure;
      setError({ message: errorMessage(cause), conflict: failure.code === 409 });
    } finally {
      setBusy('');
    }
  };

  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && opened) {
        event.preventDefault();
        if (dirty) setReview(true);
      }
    };
    const leave = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener('keydown', keys);
    window.addEventListener('beforeunload', leave);
    return () => {
      window.removeEventListener('keydown', keys);
      window.removeEventListener('beforeunload', leave);
    };
  }, [dirty, opened]);

  const createSkill = () => {
    if (!newSkill || !SKILL_NAME.test(newSkill.name)) return;
    const path =
      target.kind === 'project'
        ? `.claude/skills/${newSkill.name}/SKILL.md`
        : `claude/skills/${newSkill.name}/SKILL.md`;
    const content = skillTemplate(newSkill.name, newSkill.description);
    setOpened({
      path,
      readers: ['claude'],
      exists: false,
      size: null,
      sha256: null,
      updated_at: null,
      skill: newSkill.name,
      content: '',
    });
    setText(content);
    setNewSkill(null);
    setNotice(t('Новый навык — проверьте текст и сохраните.'));
  };

  const remove = async () => {
    if (!opened?.sha256) return;
    setRemoving(false);
    setBusy('delete');
    try {
      await workerCall(target, { op: 'delete', path: opened.path, base_sha256: opened.sha256 });
      setOpened(null);
      setText('');
      setNotice(t('Навык удалён'));
      void load();
    } catch (cause) {
      setError({ message: errorMessage(cause), conflict: (cause as Failure).code === 409 });
    } finally {
      setBusy('');
    }
  };

  const showHistory = async () => {
    if (!opened) return;
    setBusy('history');
    try {
      setHistory((await workerCall<{ backups: Backup[] }>(target, { op: 'backups', path: opened.path })).backups);
    } catch (cause) {
      setError({ message: errorMessage(cause), conflict: false });
    } finally {
      setBusy('');
    }
  };
  const restore = async (backup: Backup) => {
    if (!opened) return;
    setHistory(null);
    setBusy('save');
    try {
      await workerCall(target, {
        op: 'restore',
        path: opened.path,
        backup: backup.id,
        ...(opened.sha256 ? { base_sha256: opened.sha256 } : {}),
      });
      await open(opened.path);
      setNotice(t('Версия возвращена'));
    } catch (cause) {
      setError({ message: errorMessage(cause), conflict: (cause as Failure).code === 409 });
      setBusy('');
    }
  };

  const groups = useMemo(() => {
    const result = new Map<string, FileEntry[]>();
    for (const file of listing?.files ?? []) {
      const key = groupOf(target, file);
      result.set(key, [...(result.get(key) ?? []), file]);
    }
    return result;
  }, [listing, target]);
  const groupTitle = (key: string) =>
    key === 'project'
      ? t('Проект')
      : key === 'skills'
        ? t('Навыки проекта')
        : key === 'shared'
          ? t('Общие для воркера')
          : t('Только аккаунт {0}', accountName(key.slice('account:'.length)));

  const scopeLine = (file: FileEntry) => {
    const readers = file.readers.map((reader) => READER_LABELS[reader] ?? reader).join(', ');
    if (target.kind === 'project') return t('Читает: {0} · действует на все сессии проекта', readers);
    const names = (file.accounts ?? []).map(accountName);
    return names.length
      ? t('Читает: {0} · действует на аккаунты: {1}', readers, names.join(', '))
      : t('Читает: {0} · сейчас ни один аккаунт этого воркера его не использует', readers);
  };
  const lines = Math.max(1, text.split('\n').length);
  const bytes = new Blob([text]).size;
  const backHref = target.kind === 'project' ? `/projects/${target.id}` : '/settings/workers';

  return (
    <div className="instructions-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {target.kind === 'project' ? t('ПРОЕКТ {0}', target.id) : t('ВОРКЕР {0}', target.id)}
          </p>
          <h1>{t('Инструкции агентов')}</h1>
          <p className="muted">
            {target.kind === 'project'
              ? t('Что агенты читают перед работой в этом проекте: AGENTS.md, CLAUDE.md и навыки.')
              : t('Общие инструкции и навыки на этом воркере — для всех или отдельных аккаунтов.')}
          </p>
        </div>
        <Link className="ui-button ui-button-secondary" to={backHref}>
          {t('Назад')}
        </Link>
      </div>
      {listError && <ErrorBanner message={listError} onRetry={() => void load()} />}
      <div className="instructions-layout">
        <aside className="panel instructions-files" aria-label={t('Файлы')}>
          {!listing && !listError ? (
            <Loading />
          ) : (
            <>
              {[...groups.entries()].map(([key, files]) => (
                <section key={key}>
                  <h2>{groupTitle(key)}</h2>
                  <ul>
                    {files.map((file) => (
                      <li key={file.path}>
                        <button
                          type="button"
                          className={opened?.path === file.path ? 'active' : undefined}
                          onClick={() => choose(file.path)}
                        >
                          <span className="instructions-file-name">
                            {fileTitle(file.path)}
                            {opened?.path === file.path && dirty && (
                              <i className="instructions-dirty" title={t('Есть несохранённые правки')} />
                            )}
                          </span>
                          <small className="muted">
                            {file.exists
                              ? file.readers.map((reader) => READER_LABELS[reader] ?? reader).join(' · ')
                              : t('ещё не создан')}
                          </small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              <button
                type="button"
                className="button-secondary"
                onClick={() => setNewSkill({ name: '', description: '' })}
              >
                {t('+ Новый навык')}
              </button>
              {listing && target.kind === 'project' && !listing.git && (
                <p className="muted">{t('Папка проекта — не git-репозиторий: правки сохраняются без коммита.')}</p>
              )}
            </>
          )}
        </aside>
        <section className="panel instructions-editor">
          {!opened ? (
            <div className="instructions-empty">
              {busy === 'open' ? <Loading /> : <p className="muted">{t('Выберите файл слева.')}</p>}
            </div>
          ) : (
            <>
              <header className="instructions-editor-head">
                <div>
                  <h2>{opened.path}</h2>
                  <small className="muted">{scopeLine(opened)}</small>
                </div>
                <div className="stats-periods" role="tablist" aria-label={t('Режим')}>
                  {(
                    [
                      ['edit', 'Правка'],
                      ['preview', 'Просмотр'],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={mode === value}
                      className={mode === value ? 'active' : ''}
                      onClick={() => setMode(value)}
                    >
                      {t(label)}
                    </button>
                  ))}
                </div>
              </header>
              {error && (
                <div className="instructions-error" role="alert">
                  <span>{error.message}</span>
                  {error.conflict && (
                    <button type="button" className="button-secondary" onClick={() => void open(opened.path)}>
                      {t('Загрузить версию с воркера')}
                    </button>
                  )}
                </div>
              )}
              {notice && !error && (
                <p className="instructions-notice" role="status">
                  {notice}
                </p>
              )}
              {mode === 'edit' ? (
                <div className="instructions-code">
                  <div className="instructions-gutter" ref={gutter} aria-hidden="true">
                    {Array.from({ length: lines }, (_, index) => (
                      <span key={index}>{index + 1}</span>
                    ))}
                  </div>
                  <textarea
                    ref={area}
                    value={text}
                    spellCheck={false}
                    aria-label={t('Текст файла')}
                    onChange={(event) => {
                      setText(event.target.value);
                      setNotice('');
                    }}
                    onScroll={(event) => {
                      if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop;
                    }}
                  />
                </div>
              ) : (
                <div className="instructions-preview">
                  <MarkdownView content={text} />
                </div>
              )}
              <footer className="instructions-editor-foot">
                <small className={bytes > MAX_BYTES * 0.9 ? 'instructions-size-warn' : 'muted'}>
                  {t('{0} КБ из 256', (bytes / 1024).toFixed(1))}
                </small>
                {target.kind === 'worker' && opened.exists && (
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={Boolean(busy)}
                    onClick={() => void showHistory()}
                  >
                    {t('История')}
                  </button>
                )}
                {opened.skill && opened.exists && (
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={Boolean(busy)}
                    onClick={() => setRemoving(true)}
                  >
                    {t('Удалить навык')}
                  </button>
                )}
                <button
                  type="button"
                  disabled={!dirty || Boolean(busy) || bytes > MAX_BYTES}
                  onClick={() => setReview(true)}
                >
                  {busy === 'save' ? t('Сохраняю…') : t('Сохранить')}
                </button>
              </footer>
            </>
          )}
        </section>
      </div>

      {review && opened && (
        <Dialog
          open
          title={t('Сохранить {0}?', opened.path)}
          onClose={() => setReview(false)}
          className="instructions-dialog"
        >
          <p className="muted">
            {target.kind === 'project'
              ? listing?.git
                ? t('Будет коммит только этого файла в репозитории проекта (без отправки на GitHub).')
                : t('Файл будет сохранён без коммита.')
              : t('Прошлая версия сохранится в истории. {0}', scopeLine(opened))}
          </p>
          <Diff before={opened.content} after={text} />
          <div className="ui-dialog-actions">
            <button type="button" className="button-secondary" onClick={() => setReview(false)}>
              {t('Отмена')}
            </button>
            <button type="button" onClick={() => void save()}>
              {t('Сохранить')}
            </button>
          </div>
        </Dialog>
      )}

      {newSkill && (
        <Dialog open title={t('Новый навык')} onClose={() => setNewSkill(null)}>
          <form
            className="instructions-skill-form"
            onSubmit={(event) => {
              event.preventDefault();
              createSkill();
            }}
          >
            <label>
              {t('Имя')}
              <input
                autoFocus
                value={newSkill.name}
                aria-invalid={Boolean(newSkill.name) && !SKILL_NAME.test(newSkill.name)}
                onChange={(event) => setNewSkill({ ...newSkill, name: event.target.value.trim() })}
                placeholder="release-notes"
              />
              <small className={newSkill.name && !SKILL_NAME.test(newSkill.name) ? 'field-error' : 'muted'}>
                {t('Строчные латинские буквы, цифры и дефис, до 64 символов.')}
              </small>
            </label>
            <label>
              {t('Когда применять')}
              <input
                value={newSkill.description}
                onChange={(event) => setNewSkill({ ...newSkill, description: event.target.value })}
                placeholder={t('Например: когда просят подготовить заметки к релизу')}
              />
            </label>
            <div className="ui-dialog-actions">
              <button type="button" className="button-secondary" onClick={() => setNewSkill(null)}>
                {t('Отмена')}
              </button>
              <button type="submit" disabled={!SKILL_NAME.test(newSkill.name)}>
                {t('Создать')}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {history && opened && (
        <Dialog
          open
          title={t('История {0}', opened.path)}
          onClose={() => setHistory(null)}
          className="instructions-dialog"
        >
          {history.length === 0 ? (
            <p className="muted">{t('Прошлых версий пока нет.')}</p>
          ) : (
            <ul className="instructions-history">
              {history.map((backup) => (
                <li key={backup.id}>
                  <details>
                    <summary>
                      {new Date(
                        backup.id.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2}).*$/, '$1-$2-$3T$4:$5:$6Z'),
                      ).toLocaleString()}
                      <span className="muted"> · {(backup.size / 1024).toFixed(1)} КБ</span>
                    </summary>
                    <Diff before={opened.content} after={backup.content} />
                    <button type="button" onClick={() => void restore(backup)}>
                      {t('Вернуть эту версию')}
                    </button>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </Dialog>
      )}

      <ConfirmDialog
        open={removing}
        title={t('Удалить навык?')}
        name={opened?.skill ?? undefined}
        description={t('Навык исчезнет у всех агентов, которые его читают.')}
        confirmLabel={t('Удалить')}
        onConfirm={() => void remove()}
        onClose={() => setRemoving(false)}
      />
      <ConfirmDialog
        open={pending !== null}
        title={t('Есть несохранённые правки')}
        description={t('Перейти к другому файлу и потерять их?')}
        confirmLabel={t('Перейти')}
        onConfirm={() => {
          const path = pending;
          setPending(null);
          if (path) void open(path);
        }}
        onClose={() => setPending(null)}
      />
    </div>
  );
}

export function ProjectInstructions(): JSX.Element {
  const { id = '' } = useParams();
  return <Instructions key={`project:${id}`} target={{ kind: 'project', id }} />;
}

export function WorkerInstructions(): JSX.Element {
  const { id = '' } = useParams();
  return <Instructions key={`worker:${id}`} target={{ kind: 'worker', id }} />;
}
