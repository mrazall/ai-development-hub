import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../../api/useApi';
import type {
  EfficiencyResponse,
  Observation,
  TaskDetail,
  TaskRow,
  TasksResponse,
  Trigger,
} from '../../api/types-efficiency';
import { Dialog, ErrorBanner, Loading, StatusBadge } from '../../components/ui';
import { DailyChart, money, tokens, type Column } from '../../components/stats/charts';
import { t } from '../../i18n';

type UsageLists = {
  by_model: { model: string }[];
  by_account: { account_id: string | null; name: string }[];
  by_project: { project_id: string | null }[];
};

const NONE = '—';
const orNone = <T,>(value: T | null | undefined, format: (value: T) => string) =>
  value === null || value === undefined ? NONE : format(value);
const share = (value: number) => `${Math.round(value * 100)}%`;
/** Seconds as a person reads them: 45 с, 12 мин, 3 ч 20 мин, 2 д 4 ч. */
function duration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return t('{0} с', s);
  const minutes = Math.round(s / 60);
  if (minutes < 60) return t('{0} мин', minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? t('{0} ч {1} мин', hours, minutes % 60) : t('{0} ч', hours);
  const daysCount = Math.floor(hours / 24);
  return hours % 24 ? t('{0} д {1} ч', daysCount, hours % 24) : t('{0} д', daysCount);
}
const tokensOrNone = (value: number | null | undefined) => orNone(value, tokens);
const moneyOrNone = (value: number | null | undefined) => orNone(value, money);

const ROLES: Record<string, string> = {
  orchestrator: 'Оркестратор',
  executor: 'Исполнители',
  single: 'Одиночные агенты',
};
const TRIGGERS: Record<Trigger, string> = {
  initial: 'Первый запуск',
  continue: 'Продолжение',
  auto_resume: 'Автовозобновление после лимита',
  retry_after_failure: 'Повтор после ошибки',
  rework: 'Доработка',
  unknown: 'Не определено',
};
const STATUSES = ['draft', 'ready', 'queued', 'in_progress', 'review', 'done', 'cancelled'];
const STATUS_TEXT: Record<string, string> = {
  draft: 'Черновик',
  ready: 'Готова',
  queued: 'В очереди',
  in_progress: 'В работе',
  review: 'На проверке',
  done: 'Принята',
  cancelled: 'Отменена',
};
const METRICS = [
  ['tokens', 'Токены'],
  ['cost', 'Стоимость по API'],
  ['per_task', 'Стоимость на принятую задачу'],
] as const;
const SORTS: [string, string][] = [
  ['cost', 'По API'],
  ['tokens', 'Токены'],
  ['wall', 'Время'],
  ['retries', 'Повторы'],
];

function observationText(item: Observation, titles: Map<string, string>): string {
  const task = titles.get(String(item.subject.task_id ?? '')) ?? String(item.subject.task_id ?? '');
  const p = item.params as Record<string, number>;
  switch (item.code) {
    case 'task_cost_above_median':
      return t(
        '«{0}» стоила {1} — больше трёх медиан принятых задач ({2}, задач: {3}).',
        task,
        money(p.cost_usd),
        money(p.median_cost_usd),
        p.n,
      );
    case 'orchestrator_cost_majority':
      return t(
        '«{0}»: на оркестратора пришлось {1} стоимости оркестрации. Само по себе это не плохо.',
        task,
        share(p.share),
      );
    case 'repeated_retries':
      return t('«{0}»: {1} подтверждённых повтора после ошибок.', task, p.retries);
    case 'duration_unknown':
      return t('Для {0} из {1} задач длительность нельзя посчитать достоверно.', p.tasks, p.total);
    default:
      return item.code;
  }
}

const CRITERIA: Record<string, string> = {
  task_cost_above_median: 'стоимость больше 3 медиан принятых задач с полной ценой (их не меньше 5)',
  orchestrator_cost_majority: 'на оркестратора больше 50 % стоимости оркестрации; цены точные, всего не меньше $1',
  repeated_retries: 'не меньше 2 подтверждённых повторов после ошибки',
  duration_unknown: 'в событиях статуса нет подтверждённых начала и конца работы',
};

function warningText(code: string, params: Record<string, unknown>): string {
  switch (code) {
    case 'cost_partial':
      return t('Стоимость неполная: у части моделей нет цены.');
    case 'duration_unknown':
      return t('Длительность неизвестна: нет подтверждённых начала и конца.');
    case 'duration_estimated':
      return t('Длительность оценочная.');
    case 'attribution_estimated':
      return t(
        'Модель и аккаунт для {0} из {1} прогонов восстановлены приблизительно (старые события).',
        String(params.runs),
        String(params.total),
      );
    default:
      return code;
  }
}

/** Horizontal bar split by role: one for tokens, one for cost — the two shares are never mixed. */
function RoleSplit({ data }: { data: EfficiencyResponse['by_role'] }): JSX.Element {
  const rows: [string, (role: EfficiencyResponse['by_role'][number]) => number | null][] = [
    [t('Доля токенов'), (role) => role.token_share],
    [t('Доля стоимости'), (role) => role.cost_share],
  ];
  const slot = (role: string) => (role === 'orchestrator' ? 1 : role === 'executor' ? 2 : 3);
  return (
    <section className="panel stats-chart efficiency-roles">
      <div className="panel-heading">
        <h2>{t('Оркестратор и исполнители')}</h2>
      </div>
      {data.length ? (
        <>
          {rows.map(([label, value]) => (
            <div className="efficiency-split" key={label}>
              <span className="muted">{label}</span>
              <div className="efficiency-split-bar" role="img" aria-label={label}>
                {data.map((role) => {
                  const part = value(role);
                  return part ? (
                    <i
                      key={role.role}
                      className={`stats-series-${slot(role.role)}`}
                      style={{ width: `${part * 100}%` }}
                      title={`${t(ROLES[role.role])}: ${share(part)}`}
                    />
                  ) : null;
                })}
              </div>
            </div>
          ))}
          <table className="efficiency-mini">
            <tbody>
              {data.map((role) => (
                <tr key={role.role}>
                  <td>
                    <i className={`stats-swatch stats-series-${slot(role.role)}`} /> {t(ROLES[role.role])}
                  </td>
                  <td>{tokens(role.tokens)}</td>
                  <td>
                    {money(role.cost_usd)}
                    {role.cost_partial ? '*' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p className="muted">{t('Нет данных')}</p>
      )}
    </section>
  );
}

function Triggers({
  data,
  context,
}: {
  data: EfficiencyResponse['by_trigger'];
  context: EfficiencyResponse['context'];
}): JSX.Element {
  const top = Math.max(...data.map((item) => item.tokens), 1);
  return (
    <section className="panel stats-chart efficiency-triggers">
      <div className="panel-heading">
        <h2>{t('Почему запускались агенты')}</h2>
      </div>
      <table className="efficiency-mini">
        <tbody>
          {data.map((item) => (
            <tr key={item.trigger}>
              <td>{t(TRIGGERS[item.trigger] ?? item.trigger)}</td>
              <td className="muted">{t('{0} прогонов', item.runs)}</td>
              <td>
                <span className="stats-share">
                  <span style={{ width: `${(item.tokens / top) * 100}%` }} />
                </span>
                {tokens(item.tokens)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted efficiency-context">
        {t('Кэш: {0} входа', orNone(context.cache_read_share, share))} ·{' '}
        {t('сжатий контекста: {0}', orNone(context.compactions, String))} ·{' '}
        {t('на продолжения: {0}', tokens(context.continuation_tokens))}
      </p>
    </section>
  );
}

function Detail({ id, filters, onClose }: { id: string; filters: string; onClose: () => void }): JSX.Element {
  const result = useApi<TaskDetail>(`/stats/tasks/${encodeURIComponent(id)}?${filters}`);
  const d = result.data;
  return (
    <Dialog
      open
      title={d?.title || t('Задача')}
      onClose={onClose}
      className="efficiency-detail"
      data-testid="efficiency-task-detail"
    >
      {result.loading && !d ? (
        <Loading />
      ) : result.error ? (
        <ErrorBanner message={result.error} />
      ) : (
        d && (
          <div className="efficiency-detail-body">
            <div className="stats-tiles">
              <article className="panel stats-tile">
                <span>{t('Токены')}</span>
                <strong>{tokens(d.tokens)}</strong>
                <small className="muted">
                  {t('оркестратор {0} · исполнители {1}', tokens(d.orchestrator.tokens), tokens(d.executors.tokens))}
                </small>
              </article>
              <article className="panel stats-tile">
                <span>{t('По API')}</span>
                <strong>
                  {moneyOrNone(d.cost_usd)}
                  {d.cost_partial ? '*' : ''}
                </strong>
                <small className="muted">
                  {t(
                    'оркестратор {0} · исполнители {1}',
                    moneyOrNone(d.orchestrator.cost_usd),
                    moneyOrNone(d.executors.cost_usd),
                  )}
                </small>
              </article>
              <article className="panel stats-tile">
                <span>{t('Время')}</span>
                <strong>{orNone(d.wall_s, duration)}</strong>
                <small className="muted">{t('агенты работали {0}', orNone(d.active_s, duration))}</small>
              </article>
            </div>
            {d.warnings.length > 0 && (
              <ul className="efficiency-warnings">
                {d.warnings.map((warning) => (
                  <li key={warning.code}>{warningText(warning.code, warning.params)}</li>
                ))}
              </ul>
            )}
            <h3>{t('Участники')}</h3>
            <div className="stats-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t('Роль')}</th>
                    <th>{t('Модель')}</th>
                    <th>{t('Аккаунт')}</th>
                    <th>{t('Статус')}</th>
                    <th>{t('Прогоны')}</th>
                    <th>{t('Токены')}</th>
                    <th>{t('По API')}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.participants.map((p) => (
                    <tr key={p.session_id}>
                      <td>
                        <Link to={`/workspace?project=${encodeURIComponent(d.project_id)}&session=${p.session_id}`}>
                          {t(ROLES[p.role ?? 'single'] ?? p.role ?? '')}
                        </Link>
                      </td>
                      <td>{p.model ?? NONE}</td>
                      <td>{p.account_name ?? p.account_id ?? NONE}</td>
                      <td>
                        <StatusBadge value={p.status} />
                      </td>
                      <td>
                        {p.runs}
                        {p.retries ? ` (${t('повторов: {0}', p.retries)})` : ''}
                      </td>
                      <td>{tokens(p.tokens)}</td>
                      <td>
                        {moneyOrNone(p.cost_usd)}
                        {p.cost_partial ? '*' : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>{t('Прогоны')}</h3>
            <div className="stats-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t('Начало')}</th>
                    <th>{t('Причина')}</th>
                    <th>{t('Модель')}</th>
                    <th>{t('Статус')}</th>
                    <th>{t('Работа')}</th>
                    <th>{t('Токены')}</th>
                    <th>{t('По API')}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.runs.map((run, index) => (
                    <tr key={run.id ?? `${run.session_id}-${index}`}>
                      <td>{run.started_at ? new Date(run.started_at).toLocaleString() : NONE}</td>
                      <td>{t(TRIGGERS[run.trigger] ?? run.trigger)}</td>
                      <td title={run.attribution === 'exact' ? undefined : t('восстановлено приблизительно')}>
                        {run.model ?? NONE}
                        {run.attribution === 'exact' ? '' : ' ≈'}
                      </td>
                      <td>
                        <StatusBadge value={run.status} />
                      </td>
                      <td>{orNone(run.active_s, duration)}</td>
                      <td>{tokens(run.tokens)}</td>
                      <td>
                        {moneyOrNone(run.cost_usd)}
                        {run.cost_partial ? '*' : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
    </Dialog>
  );
}

/** The efficiency tab: what tasks cost, how long they took, orchestrator vs executors, re-runs. */
export function Efficiency({ days }: { days: number }): JSX.Element {
  const [filter, setFilter] = useState({ project_id: '', model: '', account_id: '', role: '', status: '' });
  const [metric, setMetric] = useState<(typeof METRICS)[number][0]>('tokens');
  const [sort, setSort] = useState('cost');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const filters = new URLSearchParams({ days: String(days) });
  for (const [key, value] of Object.entries(filter)) if (value) filters.set(key, value);
  const result = useApi<EfficiencyResponse>(`/stats/efficiency?${filters}`);
  const tasks = useApi<TasksResponse>(
    `/stats/tasks?${filters}&sort=${sort}&order=desc&limit=200&q=${encodeURIComponent(query)}`,
  );
  const lists = useApi<UsageLists>(`/stats/usage?days=${days}`);
  const d = result.data;
  const titles = useMemo(
    () => new Map((tasks.data?.items ?? []).map((row) => [row.task_id, row.title || row.task_id])),
    [tasks.data],
  );
  const columns: Column[] = (d?.series ?? []).map((point) => {
    const value =
      metric === 'tokens' ? point.tokens : metric === 'cost' ? point.cost_usd : (point.cost_per_completed_task ?? 0);
    return { date: point.period, values: { total: value }, total: value };
  });
  const set = (key: keyof typeof filter, value: string) => setFilter((current) => ({ ...current, [key]: value }));
  const selects: [keyof typeof filter, string, [string, string][]][] = [
    [
      'project_id',
      'Проект',
      (lists.data?.by_project ?? []).flatMap((p) => (p.project_id ? [[p.project_id, p.project_id]] : [])),
    ],
    ['model', 'Модель', (lists.data?.by_model ?? []).map((m) => [m.model, m.model])],
    [
      'account_id',
      'Аккаунт',
      (lists.data?.by_account ?? []).flatMap((a) => (a.account_id ? [[a.account_id, a.name]] : [])),
    ],
    ['role', 'Роль', Object.entries(ROLES).map(([value, label]) => [value, t(label)])],
    ['status', 'Статус задачи', STATUSES.map((value) => [value, t(STATUS_TEXT[value])])],
  ];
  const kpi = d?.kpi;
  return (
    <>
      <div className="efficiency-filters" role="group" aria-label={t('Фильтры')}>
        {selects.map(([key, label, options]) => (
          <select
            key={key}
            value={filter[key]}
            onChange={(event) => set(key, event.target.value)}
            aria-label={t(label)}
          >
            <option value="">{t('{0}: все', t(label))}</option>
            {options.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        ))}
      </div>
      {result.error && <ErrorBanner message={result.error} />}
      {result.loading && !d ? (
        <Loading />
      ) : !d || !kpi ? null : (
        <>
          <section className="stats-tiles efficiency-tiles" aria-label={t('Итого')} data-testid="efficiency-kpi">
            <article className="panel stats-tile">
              <span>{t('Принято задач')}</span>
              <strong>{kpi.completed_tasks}</strong>
              <small className="muted">{t('только статус «Принята»')}</small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Токенов на задачу')}</span>
              <strong>{tokensOrNone(kpi.tokens_per_completed_task)}</strong>
              <small className="muted">{t('всего {0}', tokens(kpi.total_tokens))}</small>
            </article>
            <article className="panel stats-tile">
              <span>{t('По API на задачу')}</span>
              <strong>
                {moneyOrNone(kpi.cost_per_completed_task)}
                {kpi.cost_partial ? '*' : ''}
              </strong>
              <small className="muted">
                {kpi.cost_partial
                  ? t('частично: {0} токенов без цены', tokens(kpi.unpriced_tokens))
                  : t('всего {0}', money(kpi.total_cost_usd))}
              </small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Медианное время')}</span>
              <strong>{orNone(kpi.median_wall_s, duration)}</strong>
              <small className="muted">{t('от старта до конца')}</small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Доля оркестратора')}</span>
              <strong>{orNone(kpi.orchestrator_cost_share, share)}</strong>
              <small className="muted">
                {kpi.orchestrator_cost_share !== null && !kpi.orchestrator_cost_share_exact
                  ? t('оценка')
                  : t('в стоимости оркестраций')}
              </small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Повторы после ошибок')}</span>
              <strong>{kpi.confirmed_retries}</strong>
              <small className="muted">{t('подтверждённые')}</small>
            </article>
          </section>
          <div className="efficiency-charts">
            <section className="efficiency-trend">
              <select
                value={metric}
                onChange={(event) => setMetric(event.target.value as typeof metric)}
                aria-label={t('Показатель')}
              >
                {METRICS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {t(label)}
                  </option>
                ))}
              </select>
              <DailyChart
                title={d.granularity === 'week' ? t('По неделям') : t('По дням')}
                columns={columns}
                series={[{ key: 'total', label: t(METRICS.find(([value]) => value === metric)![1]), slot: 1 }]}
                format={metric === 'tokens' ? tokens : money}
              />
            </section>
            <RoleSplit data={d.by_role} />
            <Triggers data={d.by_trigger} context={d.context} />
          </div>
        </>
      )}
      <div className="efficiency-bottom">
        <section className="panel stats-table efficiency-tasks">
          <div className="panel-heading">
            <h2>{t('Задачи')}</h2>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('Поиск задачи…')}
              aria-label={t('Поиск задачи')}
            />
          </div>
          <div className="stats-table-scroll">
            {tasks.error ? (
              <ErrorBanner message={tasks.error} />
            ) : tasks.loading && !tasks.data ? (
              <Loading />
            ) : (
              <table data-testid="efficiency-tasks">
                <thead>
                  <tr>
                    <th>{t('Задача')}</th>
                    <th>{t('Проект')}</th>
                    <th>{t('Статус')}</th>
                    <th>{t('Агенты')}</th>
                    {SORTS.map(([value, label]) => (
                      <th key={value} aria-sort={sort === value ? 'descending' : undefined}>
                        <button type="button" className="efficiency-sort" onClick={() => setSort(value)}>
                          {t(label)}
                          {sort === value ? ' ↓' : ''}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(tasks.data?.items ?? []).map((row: TaskRow) => (
                    <tr key={row.task_id} className="efficiency-row" onClick={() => setSelected(row.task_id)}>
                      <td>
                        <button type="button" className="efficiency-task-link">
                          {row.title || row.task_id}
                        </button>
                      </td>
                      <td className="muted">{row.project_id}</td>
                      <td>{row.status ? <StatusBadge value={row.status} /> : NONE}</td>
                      <td>{row.agents}</td>
                      <td>
                        {moneyOrNone(row.cost_usd)}
                        {row.cost_partial ? '*' : ''}
                      </td>
                      <td>{tokens(row.tokens)}</td>
                      <td title={row.duration_basis === 'estimated' ? t('оценка') : undefined}>
                        {orNone(row.wall_s, duration)}
                        {row.duration_basis === 'estimated' ? ' ≈' : ''}
                      </td>
                      <td>{row.retries || NONE}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {tasks.data && !tasks.data.items.length && <p className="muted">{t('Задачи не найдены')}</p>}
          </div>
        </section>
        <section className="panel stats-table efficiency-observations">
          <div className="panel-heading">
            <h2>{t('Наблюдения')}</h2>
          </div>
          <div className="stats-table-scroll">
            {d?.observations.length ? (
              <ul>
                {d.observations.map((item, index) => (
                  <li key={`${item.code}-${index}`}>
                    <span>{observationText(item, titles)}</span>
                    <small className="muted">
                      {t('Критерий')}: {CRITERIA[item.code] ? t(CRITERIA[item.code]) : item.criterion}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">{t('Ничего необычного по заданным правилам.')}</p>
            )}
          </div>
        </section>
      </div>
      {selected && <Detail id={selected} filters={filters.toString()} onClose={() => setSelected(null)} />}
    </>
  );
}
