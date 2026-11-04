import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { ago, useApi } from '../../api/useApi';
import { ConfirmDialog, ErrorBanner, Loading, StatusBadge } from '../../components/ui';
import { t } from '../../i18n';
import { layoutGraph } from '../../components/repo/graphLayout';
import '../../components/repo/repo.css';

type Commit = { sha: string; parents: string[]; subject: string; author: string; at: string; refs: string[] };
type Branch = { name: string; head: string; agent_session_id: string | null; agent_session_title: string | null };
type Graph = {
  available: boolean;
  reason: string | null;
  refreshing: boolean;
  fetched_at: string | null;
  commits: Commit[];
  branches: Branch[];
  has_more: boolean;
};
type Pull = {
  number: number;
  title: string;
  author: string;
  branch: string;
  base: string;
  draft: boolean;
  mergeable: boolean | null;
  review: string | null;
  checks: { state: string; passed: number; failed: number; pending: number };
  url: string;
  updated_at: string;
};
type Job = { name: string; conclusion: string | null; duration_s: number | null; url: string | null };
type Run = {
  id: number;
  workflow: string;
  branch: string;
  event: string;
  status: string;
  conclusion: string | null;
  duration_s: number | null;
  url: string;
  jobs: Job[];
};
type Github = {
  available: boolean;
  reason: string | null;
  refreshing: boolean;
  fetched_at: string | null;
  pulls: Pull[];
  runs: Run[];
};
type Files = {
  refreshing: boolean;
  files: { path: string; added: number | null; deleted: number | null }[] | null;
  url: string | null;
};
type Action = { action: 'merge_pr' | 'close_pr' | 'rerun_failed'; target: number; description: string };

function useRepoApi<T extends { refreshing: boolean }>(path: string | null) {
  const result = useApi<T>(path, { refreshMs: 30000 });
  const started = useRef<number | null>(null);
  useEffect(() => {
    started.current = null;
  }, [path]);
  useEffect(() => {
    if (!result.data?.refreshing) {
      started.current = null;
      return;
    }
    started.current ??= Date.now();
    if (Date.now() - started.current >= 60000) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState === 'visible') result.reload();
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [result.data, result.reload]);
  return result;
}
// Nothing cached yet and the worker is still collecting: "unavailable" would be premature.
function waiting(data: { refreshing: boolean; fetched_at?: string | null }): boolean {
  return data.refreshing && !data.fetched_at;
}
function Waiting(): JSX.Element {
  return (
    <div role="status">
      <p className="muted">{t('Загружаю с воркера… первый раз это может занять до минуты')}</p>
      <Loading />
    </div>
  );
}
function duration(seconds: number | null): string {
  if (seconds == null) return t('Неизвестно');
  const value = Math.max(0, Math.round(seconds));
  return value >= 60 ? t('{0} мин {1} с', Math.floor(value / 60), value % 60) : t('{0} с', value);
}
function human(value: string | null): string {
  const labels: Record<string, string> = {
    queued: t('В очереди'),
    in_progress: t('Выполняется'),
    running: t('Выполняется'),
    completed: t('Завершено'),
    success: t('Успешно'),
    failure: t('Не пройдено'),
    cancelled: t('Отменено'),
    skipped: t('Пропущено'),
    approved: t('Одобрено'),
    changes_requested: t('Запрошены изменения'),
    review_required: t('Ожидает ревью'),
    push: t('Публикация'),
    pull_request: t('Запрос на слияние'),
    workflow_dispatch: t('Ручной запуск'),
    schedule: t('По расписанию'),
  };
  return (value && labels[value]) || t('Неизвестно');
}
export function ProjectTabs({ id, active }: { id: string; active: 'overview' | 'repo' | 'files' }): JSX.Element {
  const tab = (value: typeof active, to: string, label: string) => (
    <Link className={active === value ? 'active' : ''} to={to}>
      {label}
    </Link>
  );
  return (
    <nav className="stats-periods repo-tabs" aria-label={t('Раздел проекта')}>
      {tab('overview', `/projects/${id}`, t('Обзор'))}
      {tab('repo', `/projects/${id}/repo`, t('Репозиторий и GitHub'))}
      {tab('files', `/projects/${id}/files`, t('Файлы'))}
    </nav>
  );
}
function GraphView({
  graph,
  pulls,
  select,
}: {
  graph: Graph;
  pulls: Pull[];
  select: (sha: string) => void;
}): JSX.Element {
  const layout = useMemo(() => layoutGraph(graph.commits), [graph.commits]);
  const maxLane = Math.max(
    0,
    ...layout.flatMap((row) => [row.lane, ...row.edges.flatMap((edge) => [edge.start, edge.end])]),
  );
  const labelX = 35 + (maxLane + 1) * 20;
  const labelWidth = 600;
  return (
    <svg
      data-testid="repo-graph"
      width={Math.max(720, labelX + labelWidth)}
      height={Math.max(80, layout.length * 48 + 20)}
      role="img"
      aria-label={t('Граф коммитов')}
    >
      {layout.map(({ commit, lane, edges }, index) => {
        const y = 25 + index * 48;
        const x = 25 + lane * 20;
        const refs = [
          ...new Set([
            ...commit.refs.filter(
              (ref) => !graph.branches.some((branch) => branch.name === ref && branch.agent_session_id),
            ),
            ...graph.branches
              .filter((branch) => branch.head === commit.sha)
              .filter((branch) => !branch.agent_session_id)
              .map((branch) => branch.name),
            ...pulls
              .filter((pull) =>
                graph.branches.some(
                  (branch) =>
                    branch.head === commit.sha &&
                    (branch.name === pull.branch || branch.name === `origin/${pull.branch}`),
                ),
              )
              .map((pull) => `PR #${pull.number}`),
          ]),
        ];
        return (
          <g key={commit.sha}>
            {edges.map((edge, i) => {
              const x1 = 25 + edge.start * 20;
              const x2 = 25 + edge.end * 20;
              const y1 = edge.kind === 'parent' ? y : y - 24;
              const y2 = edge.kind === 'join' ? y : y + 24;
              return (
                <path
                  key={i}
                  data-testid={edge.kind === 'parent' ? 'repo-edge' : undefined}
                  data-from={edge.from}
                  data-to={edge.to}
                  d={`M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}`}
                  fill="none"
                  stroke={`var(--series-${(edge.start % 4) + 1})`}
                  strokeWidth="2"
                />
              );
            })}
            {edges
              .filter((edge) => edge.kind === 'parent')
              .map((edge, i) => (
                <line
                  key={`tail-${i}`}
                  x1={25 + edge.end * 20}
                  x2={25 + edge.end * 20}
                  y1={y + 24}
                  y2={y + 48}
                  stroke={`var(--series-${(edge.end % 4) + 1})`}
                  strokeWidth="2"
                />
              ))}
            <circle
              data-testid="repo-commit"
              data-sha={commit.sha}
              cx={x}
              cy={y}
              r="6"
              fill={`var(--series-${(lane % 4) + 1})`}
              tabIndex={0}
              onClick={() => select(commit.sha)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') select(commit.sha);
              }}
            >
              <title>{`${commit.sha}\n${commit.author}\n${new Date(commit.at).toLocaleString()}\n${commit.subject}`}</title>
            </circle>
            <foreignObject x={labelX} y={y - 19} width={labelWidth} height="42">
              <div className="repo-graph-label">
                {refs.map((ref) => (
                  <span className="repo-ref" data-testid="repo-ref" data-sha={commit.sha} key={ref}>
                    {ref}
                  </span>
                ))}{' '}
                {graph.branches
                  .filter((branch) => branch.head === commit.sha && branch.agent_session_id)
                  .map((branch) => (
                    <Link
                      data-testid="repo-agent-branch"
                      title={branch.name}
                      className="repo-ref"
                      key={branch.name}
                      to={`/sessions/${branch.agent_session_id}`}
                    >
                      {branch.agent_session_title || branch.name}
                    </Link>
                  ))}{' '}
                <span className="repo-subject">{commit.subject}</span>
              </div>
            </foreignObject>
          </g>
        );
      })}
    </svg>
  );
}
export function Repo(): JSX.Element {
  const { id = '' } = useParams();
  const [limit, setLimit] = useState(200);
  const [sha, setSha] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [error, setError] = useState('');
  const project = useApi<{ name: string; repo_url: string | null }>(`/projects/${id}`);
  const graph = useRepoApi<Graph>(`/projects/${id}/repo/graph?limit=${limit}`);
  const github = useRepoApi<Github>(`/projects/${id}/repo/github`);
  const files = useRepoApi<Files>(sha ? `/projects/${id}/repo/commits/${sha}` : null);
  const commitUrl = files.data?.url;
  const badge = (value: string | null) => {
    const tone =
      value === 'success'
        ? 'completed'
        : value === 'failure'
          ? 'failed'
          : value === 'in_progress'
            ? 'running'
            : value || 'unknown';
    return <StatusBadge value={tone} label={human(value)} />;
  };
  const perform = () => {
    if (!action) return;
    const current = action;
    setAction(null);
    setError('');
    void api(`/projects/${id}/repo/actions`, {
      method: 'POST',
      body: `{"action":"${current.action}","target":"${current.target}","confirm":true}`,
    }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : t('Не удалось выполнить действие')));
  };
  return (
    <div className="stats-page repo-page">
      <div className="page-heading">
        <div>
          <Link to="/projects" className="back-link">
            {t('← Все проекты')}
          </Link>
          <p className="eyebrow">{t('ПРОЕКТ')}</p>
          <h1>{project.data?.name || t('Репозиторий')}</h1>
          <ProjectTabs id={id} active="repo" />
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      <div className="repo-layout">
        <section className="panel repo-panel">
          <div className="panel-heading">
            <h2>{t('Граф коммитов')}</h2>
            <small>
              {graph.data?.refreshing && t('Обновление…')}{' '}
              {graph.data?.fetched_at && t('Обновлено {0}', ago(graph.data.fetched_at))}
            </small>
          </div>
          <div className="repo-scroll">
            {graph.error ? (
              <ErrorBanner message={graph.error} />
            ) : !graph.data || waiting(graph.data) ? (
              <Waiting />
            ) : !graph.data.available ? (
              <p>{graph.data.reason || t('Репозиторий не найден на воркерах проекта')}</p>
            ) : (
              <>
                <GraphView graph={graph.data} pulls={github.data?.pulls || []} select={setSha} />
                {graph.data.has_more && <button onClick={() => setLimit(limit + 200)}>{t('Показать ещё')}</button>}
              </>
            )}
          </div>
          {sha && (
            <div className="repo-files" data-testid="repo-commit-files">
              <button onClick={() => setSha(null)} aria-label={t('Закрыть')}>
                ×
              </button>
              <h3>{t('Файлы коммита')}</h3>
              <small>{sha}</small>
              {files.data?.refreshing && <p>{t('Обновление…')}</p>}
              {files.error && <ErrorBanner message={files.error} />}
              {files.data?.files?.map((file) => (
                <div key={file.path}>
                  {file.path} {file.added != null && `+${file.added}`} {file.deleted != null && `−${file.deleted}`}
                </div>
              ))}
              {commitUrl && (
                <a href={commitUrl} target="_blank" rel="noreferrer">
                  {t('Открыть на GitHub')}
                </a>
              )}
            </div>
          )}
        </section>
        <div className="repo-right">
          <section className="panel repo-panel">
            <div className="panel-heading">
              <h2>{t('Запросы на слияние')}</h2>
              <small>
                {github.data?.refreshing && t('Обновление…')}{' '}
                {github.data?.fetched_at && t('Обновлено {0}', ago(github.data.fetched_at))}
              </small>
            </div>
            <div className="repo-scroll">
              {github.error ? (
                <ErrorBanner message={github.error} />
              ) : !github.data || waiting(github.data) ? (
                <Waiting />
              ) : !github.data.available ? (
                <p>{github.data.reason || t('GitHub недоступен')}</p>
              ) : github.data.pulls.length === 0 ? (
                <p>{t('Нет открытых PR')}</p>
              ) : (
                github.data.pulls.map((pull) => {
                  const why =
                    pull.checks.state === 'failure'
                      ? t('Проверки не пройдены')
                      : pull.mergeable === false
                        ? t('Есть конфликт слияния')
                        : '';
                  return (
                    <article className="repo-row" data-testid="repo-pr-row" data-number={pull.number} key={pull.number}>
                      <strong className="repo-title">
                        <a href={pull.url}>
                          #{pull.number} {pull.title}
                        </a>
                      </strong>
                      <p>
                        {pull.author} · {pull.branch} → {pull.base}
                      </p>
                      <p>
                        {pull.draft && <span>{t('Черновик')} · </span>}
                        {pull.mergeable === false && <span>{t('Конфликт')} · </span>}
                        {human(pull.review)}
                      </p>
                      <div className="repo-actions">
                        <span data-testid="repo-pr-checks" className={`repo-checks repo-checks-${pull.checks.state}`}>
                          <span className="repo-check-success">{pull.checks.passed} ✓</span>
                          {pull.checks.failed > 0 && (
                            <>
                              {' '}
                              · <span className="repo-check-failure">{pull.checks.failed} ✗</span>
                            </>
                          )}
                          {pull.checks.pending > 0 && (
                            <>
                              {' '}
                              · <span className="repo-check-pending">{pull.checks.pending} ⏳</span>
                            </>
                          )}
                        </span>
                        <small>{t('Обновлено {0}', ago(pull.updated_at))}</small>
                        <button
                          data-testid="repo-pr-merge"
                          disabled={!!why}
                          title={why || undefined}
                          onClick={() =>
                            setAction({
                              action: 'merge_pr',
                              target: pull.number,
                              description: `#${pull.number} ${pull.title}`,
                            })
                          }
                        >
                          {t('Слить')}
                        </button>
                        <button
                          data-testid="repo-pr-close"
                          onClick={() =>
                            setAction({
                              action: 'close_pr',
                              target: pull.number,
                              description: `#${pull.number} ${pull.title}`,
                            })
                          }
                        >
                          {t('Закрыть PR')}
                        </button>
                      </div>
                    </article>
                  );
                })
              )}
            </div>
          </section>
          <section className="panel repo-panel">
            <div className="panel-heading">
              <h2>{t('Прогоны CI')}</h2>
            </div>
            <div className="repo-scroll">
              {!github.error && (!github.data || waiting(github.data)) && <Waiting />}
              {github.data?.available && github.data.runs.length === 0 && <p>{t('Нет прогонов CI')}</p>}
              {github.data?.runs.map((run) => (
                <article className="repo-row" data-testid="repo-run-row" data-id={run.id} key={run.id}>
                  <div className="repo-run-line">
                    <button
                      className="repo-run-toggle"
                      data-testid="repo-run-toggle"
                      onClick={() => setExpanded(expanded === run.id ? null : run.id)}
                      aria-expanded={expanded === run.id}
                    >
                      {expanded === run.id ? '▾' : '▸'} {run.workflow}
                    </button>
                    <span className="repo-run-meta">
                      {run.branch} · {human(run.event)} · {duration(run.duration_s)}
                    </span>
                    {badge(run.conclusion || run.status)}
                    {run.conclusion === 'failure' && (
                      <button
                        data-testid="repo-run-rerun"
                        onClick={() => setAction({ action: 'rerun_failed', target: run.id, description: run.workflow })}
                      >
                        {t('Перезапустить упавшие')}
                      </button>
                    )}
                  </div>
                  {expanded === run.id && (
                    <div>
                      {run.jobs.map((job, index) => (
                        <div data-testid="repo-run-job" key={`${job.name}-${index}`}>
                          {job.name} · {badge(job.conclusion)} · {duration(job.duration_s)}{' '}
                          {job.url && <a href={job.url}>{t('Журнал')}</a>}
                        </div>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>
      <ConfirmDialog
        open={!!action}
        title={
          action?.action === 'merge_pr'
            ? t('Слить PR?')
            : action?.action === 'close_pr'
              ? t('Закрыть PR?')
              : t('Перезапустить упавшие задачи?')
        }
        description={action?.description}
        confirmLabel={
          action?.action === 'merge_pr'
            ? t('Слить')
            : action?.action === 'close_pr'
              ? t('Закрыть PR')
              : t('Перезапустить упавшие')
        }
        onClose={() => setAction(null)}
        onConfirm={perform}
      />
    </div>
  );
}
