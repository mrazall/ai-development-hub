import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useApi } from '../api/useApi';
import { ErrorBanner, Loading, SplitPane } from '../components/ui';
import { t } from '../i18n';

type Entry = { name: string; type: 'file' | 'dir'; size?: number; path?: string };
type FileResponse = { path: string; size: number; truncated: boolean; binary: boolean; content: string | null };
type GitStatus = {
  branch: string;
  ahead: number;
  behind: number;
  files: { path: string; index: string; worktree: string }[];
};
type DiffResponse = { diff: string; truncated: boolean };
type Commit = { hash: string; author: string; time: string; subject: string };

function workerError(error: string): string {
  return /503|504|worker/i.test(error) ? t('Worker недоступен. Проверьте соединение и попробуйте снова.') : error;
}

export function SessionFiles(): JSX.Element {
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const path = params.get('path') ?? '';
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState<'code' | 'changes' | 'history'>('code');
  const tree = useApi<{ path: string; entries: Entry[] }>(`/sessions/${id}/files?path=`);
  const file = useApi<FileResponse>(
    path && tab === 'code' ? `/sessions/${id}/file?path=${encodeURIComponent(path)}` : null,
  );
  const status = useApi<GitStatus>(tab === 'changes' ? `/sessions/${id}/git/status` : null);
  const diff = useApi<DiffResponse>(
    tab === 'changes' && path ? `/sessions/${id}/git/diff?path=${encodeURIComponent(path)}&staged=0` : null,
  );
  const history = useApi<Commit[]>(tab === 'history' ? `/sessions/${id}/git/log?limit=50` : null);
  const entries = useMemo(
    () => (tree.data?.entries ?? []).filter((entry) => entry.name.toLowerCase().includes(query.toLowerCase())),
    [tree.data, query],
  );
  const selectPath = (value: string) => {
    setParams({ path: value });
    setTab('code');
  };
  return (
    <>
      <Link className="back-link" to={`/workspace?session=${id}`}>
        {t('← Рабочая область')}
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ФАЙЛЫ ИСПОЛНИТЕЛЯ')}</p>
          <h1>{t('Файлы и Git')}</h1>
          <p className="muted">
            {t('Сессия')} {id}
          </p>
        </div>
        <div className="file-tabs">
          {(['code', 'changes', 'history'] as const).map((item) => (
            <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>
              {item === 'code' ? t('Код') : item === 'changes' ? t('Изменения') : t('История')}
            </button>
          ))}
        </div>
      </div>
      <SplitPane className="file-layout" initial={280} min={220} max={460} storageKey={`aihub.session-files.${id}`}>
        <aside className="panel file-tree">
          <h2>{t('Дерево файлов')}</h2>
          <input
            aria-label={t('Поиск файлов')}
            placeholder={t('Поиск по имени…')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {tree.error ? (
            <ErrorBanner message={workerError(tree.error)} />
          ) : tree.loading ? (
            <Loading />
          ) : entries.length ? (
            <ul className="file-tree-list">
              {entries.map((entry) => (
                <li key={entry.name}>
                  {entry.type === 'dir' ? (
                    <span className="file-dir">📁 {entry.name}</span>
                  ) : (
                    <button
                      className={path === (entry.path ?? entry.name) ? 'selected' : ''}
                      onClick={() => selectPath(entry.path ?? entry.name)}
                    >
                      📄 {entry.name}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">{t('Файлов нет.')}</p>
          )}
        </aside>
        <section className="panel code-panel">
          {tab === 'code' && (
            <>
              {file.error && <ErrorBanner message={workerError(file.error)} />}
              {!path ? (
                <p className="muted">{t('Выберите файл слева.')}</p>
              ) : file.loading ? (
                <Loading />
              ) : file.data ? (
                <CodeView response={file.data} />
              ) : null}
            </>
          )}
          {tab === 'changes' && <GitChanges status={status} diff={diff} selectedPath={path} selectPath={selectPath} />}
          {tab === 'history' && <GitHistory state={history} />}
        </section>
      </SplitPane>
    </>
  );
}

function CodeView({ response }: { response: FileResponse }): JSX.Element {
  if (response.binary) return <p className="muted">{t('Бинарный файл нельзя показать в редакторе.')}</p>;
  return (
    <div className="code-view">
      <div className="code-meta">
        <strong>{response.path}</strong>
        <span className="muted">
          {response.size} {t('байт')}
          {response.truncated ? t(' · показан фрагмент') : ''}
        </span>
      </div>
      <pre>
        {(response.content ?? '').split('\n').map((line, index) => (
          <span id={`L${index + 1}`} key={`${index}-${line}`}>
            {String(index + 1).padStart(4, ' ')} {line}
            {'\n'}
          </span>
        ))}
      </pre>
    </div>
  );
}

function GitChanges({
  status,
  diff,
  selectedPath,
  selectPath,
}: {
  status: ReturnType<typeof useApi<GitStatus>>;
  diff: ReturnType<typeof useApi<DiffResponse>>;
  selectedPath: string;
  selectPath: (path: string) => void;
}): JSX.Element {
  if (status.error) return <ErrorBanner message={workerError(status.error)} />;
  if (status.loading && !status.data) return <Loading />;
  return (
    <div className="git-view">
      <div className="panel-heading">
        <h2>{status.data?.branch ?? t('ветка')}</h2>
        <span className="muted">
          ↑ {status.data?.ahead ?? 0} · ↓ {status.data?.behind ?? 0}
        </span>
      </div>
      <ul className="change-list">
        {(status.data?.files ?? []).map((item) => (
          <li key={item.path}>
            <button className={selectedPath === item.path ? 'selected' : ''} onClick={() => selectPath(item.path)}>
              {item.index}
              {item.worktree} {item.path}
            </button>
          </li>
        ))}
      </ul>
      {selectedPath &&
        (diff.error ? (
          <ErrorBanner message={workerError(diff.error)} />
        ) : diff.loading ? (
          <Loading />
        ) : (
          <pre className="unified-diff">{diff.data?.diff || t('Изменений нет.')}</pre>
        ))}
    </div>
  );
}

function GitHistory({ state }: { state: ReturnType<typeof useApi<Commit[]>> }): JSX.Element {
  if (state.error) return <ErrorBanner message={workerError(state.error)} />;
  if (state.loading && !state.data) return <Loading />;
  return (
    <ol className="git-history">
      {(state.data ?? []).map((commit) => (
        <li key={commit.hash}>
          <code>{commit.hash.slice(0, 8)}</code>
          <strong>{commit.subject}</strong>
          <span className="muted">
            {commit.author} · {new Date(commit.time).toLocaleString()}
          </span>
        </li>
      ))}
    </ol>
  );
}
