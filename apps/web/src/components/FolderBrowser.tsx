import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { MarkdownView } from './MarkdownView';
import { ErrorBanner, Loading } from './ui';
import { t } from '../i18n';

type Entry = { name: string; path: string; dir: boolean; size: number | null; updated_at: string };
type Listing = { path: string; entries: Entry[]; share: string | null };
type FileBody = { path: string; size: number; mime: string; updated_at: string; base64: string };

// Where agents leave files for the owner (screenshots, reports): opened first when it exists.
const SHARE = '.aihub/share';
const TEXT = /^(text\/|application\/(json|xml|javascript|x-sh|toml|yaml))/;
const TEXT_NAMES = /\.(md|txt|log|py|ts|tsx|js|jsx|json|ya?ml|toml|css|html|sh|sql|env\.example|csv)$/i;

async function filesCall<T>(base: string, body: { op: 'list' | 'read'; path: string }): Promise<T> {
  const queued = await api<{ request_id: string }>(`${base}/files`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  const started = Date.now();
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 400));
    const answer = await api<{ status: string; result?: T; error?: string }>(`/files/requests/${queued.request_id}`);
    if (answer.status === 'completed') return answer.result as T;
    if (answer.status === 'failed') throw new Error(answer.error);
    if (Date.now() - started > 40_000) throw new Error(t('Воркер не ответил за 40 с — он занят или не в сети'));
  }
}

const message = (cause: unknown) =>
  cause instanceof ApiError || cause instanceof Error ? cause.message : String(cause);

function size(bytes: number | null): string {
  if (bytes == null) return '';
  if (bytes < 1024) return t('{0} Б', bytes);
  if (bytes < 1024 * 1024) return t('{0} КБ', Math.round(bytes / 1024));
  return t('{0} МБ', (bytes / 1024 / 1024).toFixed(1));
}

function decode(body: FileBody): string {
  const bytes = Uint8Array.from(atob(body.base64), (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function Preview({ body }: { body: FileBody }): JSX.Element {
  const url = `data:${body.mime};base64,${body.base64}`;
  const name = body.path.split('/').pop() ?? body.path;
  const download = (
    <a className="ui-button ui-button-secondary" href={url} download={name}>
      {t('Скачать')}
    </a>
  );
  if (body.mime.startsWith('image/'))
    return (
      <>
        <div className="session-files-actions">{download}</div>
        <a href={url} target="_blank" rel="noreferrer" title={t('Открыть в полном размере')}>
          <img className="session-files-image" src={url} alt={name} />
        </a>
      </>
    );
  if (TEXT.test(body.mime) || TEXT_NAMES.test(name)) {
    const text = decode(body);
    return (
      <>
        <div className="session-files-actions">{download}</div>
        {name.toLowerCase().endsWith('.md') ? (
          <MarkdownView content={text} />
        ) : (
          <pre className="session-files-text">{text}</pre>
        )}
      </>
    );
  }
  return (
    <p className="muted">
      {t('Предпросмотра для этого типа нет.')} {download}
    </p>
  );
}

/** A project's folder on its worker, where its agents work: browse, preview images and text, download. */
export function FolderBrowser({ base, rootLabel }: { base: string; rootLabel: string }): JSX.Element {
  const [listing, setListing] = useState<Listing | null>(null);
  const [opened, setOpened] = useState<FileBody | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const open = useCallback(
    async (path: string) => {
      setBusy(true);
      setError('');
      try {
        setListing(await filesCall<Listing>(base, { op: 'list', path }));
        setOpened(null);
      } catch (cause) {
        setError(message(cause));
      } finally {
        setBusy(false);
      }
    },
    [base],
  );

  useEffect(() => {
    // The share folder first: that is where agents put what they made for the owner.
    let alive = true;
    (async () => {
      setBusy(true);
      try {
        const root = await filesCall<Listing>(base, { op: 'list', path: '' });
        const first = root.share ? await filesCall<Listing>(base, { op: 'list', path: SHARE }) : root;
        if (alive) setListing(first);
      } catch (cause) {
        if (alive) setError(message(cause));
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [base]);

  const read = async (entry: Entry) => {
    setBusy(true);
    setError('');
    try {
      setOpened(await filesCall<FileBody>(base, { op: 'read', path: entry.path }));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };

  // A path an agent wrote in its answer ("screenshots are in .aihub/share/login/"): a folder opens as a listing,
  // a file opens with its folder beside it. Absolute paths inside the folder are cut to relative by the worker.
  const [typed, setTyped] = useState('');
  const go = async (event: React.FormEvent) => {
    event.preventDefault();
    const path = typed.trim().replace(/^\.\//, '').replace(/\/+$/, '');
    if (!path) return;
    setBusy(true);
    setError('');
    try {
      setListing(await filesCall<Listing>(base, { op: 'list', path }));
      setOpened(null);
    } catch {
      try {
        const file = await filesCall<FileBody>(base, { op: 'read', path });
        const folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
        setListing(await filesCall<Listing>(base, { op: 'list', path: folder }));
        setOpened(file);
      } catch (cause) {
        setError(message(cause));
      }
    } finally {
      setBusy(false);
    }
  };

  const parts = listing?.path ? listing.path.split('/') : [];
  return (
    <div className="session-files">
      <nav className="session-files-crumbs" aria-label={t('Путь')}>
        <button type="button" onClick={() => open('')}>
          {rootLabel}
        </button>
        {parts.map((part, index) => (
          <span key={index}>
            {' / '}
            <button type="button" onClick={() => open(parts.slice(0, index + 1).join('/'))}>
              {part}
            </button>
          </span>
        ))}
        {listing?.path !== SHARE && (
          <button type="button" className="session-files-share" onClick={() => open(SHARE)}>
            {t('Файлы от агента')}
          </button>
        )}
        <button type="button" className="session-files-refresh" onClick={() => open(listing?.path ?? '')}>
          {t('Обновить')}
        </button>
      </nav>
      <form className="session-files-go" onSubmit={go}>
        <input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder={t('Путь из сообщения агента, например .aihub/share/screens')}
          aria-label={t('Открыть путь')}
        />
        <button type="submit" className="ui-button ui-button-secondary" disabled={busy || !typed.trim()}>
          {t('Открыть')}
        </button>
      </form>
      {error && <ErrorBanner message={error} />}
      <div className="session-files-body">
        <ul className="session-files-list" aria-label={t('Файлы')}>
          {listing?.entries.length === 0 && (
            <li className="muted">
              {listing.path === SHARE
                ? t('Агент ещё ничего не положил. Скриншоты и отчёты для вас он кладёт в .aihub/share.')
                : t('Папка пуста.')}
            </li>
          )}
          {listing?.entries.map((entry) => (
            <li key={entry.path}>
              <button
                type="button"
                className={opened?.path === entry.path ? 'active' : ''}
                onClick={() => (entry.dir ? open(entry.path) : read(entry))}
              >
                <span>{entry.dir ? `${entry.name}/` : entry.name}</span>
                <small>{size(entry.size)}</small>
              </button>
            </li>
          ))}
        </ul>
        <div className="session-files-preview">
          {busy && <Loading />}
          {!busy && opened && <Preview body={opened} />}
          {!busy && !opened && listing && <p className="muted">{t('Выберите файл слева.')}</p>}
        </div>
      </div>
    </div>
  );
}
