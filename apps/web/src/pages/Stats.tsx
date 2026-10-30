import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/useApi';
import { ErrorBanner, Loading } from '../components/ui';
import { t } from '../i18n';
import { Efficiency } from './stats/Efficiency';
import { DailyChart, days, Legend, money, tokens, type Column, type Series } from '../components/stats/charts';

type Usage = {
  input: number;
  cache_read: number;
  cache_write: number;
  output: number;
  tokens: number;
  cost_usd: number;
  unpriced_tokens: number;
  runs: number;
  sessions: number;
};
type StatsResponse = {
  days: number;
  priced_models: string[];
  total: Usage;
  by_model: (Usage & { engine: string; model: string })[];
  by_account: (Usage & { account_id: string | null; name: string })[];
  by_project: (Usage & { project_id: string | null })[];
  by_day: (Usage & { date: string; model: string })[];
};

const PERIODS = [
  [7, '7 дней'],
  [30, '30 дней'],
  [90, '90 дней'],
  [0, 'Всё время'],
] as const;
const TABLES = [
  ['model', 'По моделям'],
  ['account', 'По аккаунтам'],
  ['project', 'По проектам'],
] as const;
// Categorical slots in fixed order (validated palette); past four models the rest fold into "Other".
const SLOTS = 4;
const OTHER = '__other__';

type Row = Usage & { key: string; label: string };

/** One breakdown at a time (tabs), scrolling inside its panel. */
function UsageTable({
  tabs,
  rows,
  link,
}: {
  tabs: JSX.Element;
  rows: Row[];
  link?: (row: Row) => string | null;
}): JSX.Element {
  const top = Math.max(...rows.map((row) => row.tokens), 1);
  return (
    <section className="panel stats-table">
      <div className="panel-heading">{tabs}</div>
      <div className="stats-table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t('Название')}</th>
              <th>{t('Сессии')}</th>
              <th>{t('Вход')}</th>
              <th>{t('Кэш')}</th>
              <th>{t('Выход')}</th>
              <th>{t('Всего токенов')}</th>
              <th>{t('По API')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>{link?.(row) ? <Link to={link(row)!}>{row.label}</Link> : row.label}</td>
                <td>{row.sessions}</td>
                <td>{tokens(row.input + row.cache_write)}</td>
                <td>{tokens(row.cache_read)}</td>
                <td>{tokens(row.output)}</td>
                <td>
                  <span className="stats-share">
                    <span style={{ width: `${(row.tokens / top) * 100}%` }} />
                  </span>
                  {tokens(row.tokens)}
                </td>
                <td title={row.unpriced_tokens ? t('Без цены: {0} токенов', tokens(row.unpriced_tokens)) : undefined}>
                  {row.cost_usd || !row.unpriced_tokens ? money(row.cost_usd) : '—'}
                  {row.unpriced_tokens > 0 && row.cost_usd > 0 ? '+' : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UsageStats({ period }: { period: number }): JSX.Element {
  const [table, setTable] = useState<(typeof TABLES)[number][0]>('model');
  const result = useApi<StatsResponse>(`/stats/usage?days=${period}`);
  const data = result.data;

  const view = useMemo(() => {
    if (!data) return null;
    const ranked = data.by_model.map((row) => row.model);
    const keyOf = (model: string) => (ranked.indexOf(model) < SLOTS ? model : OTHER);
    const series: Series[] = ranked
      .slice(0, SLOTS)
      .map((model, index) => ({ key: model, label: model, slot: index + 1 }));
    if (ranked.length > SLOTS) series.push({ key: OTHER, label: t('Остальные'), slot: 0 });
    const dates = data.by_day.map((row) => row.date);
    const today = new Date().toISOString().slice(0, 10);
    const first = data.days
      ? new Date(Date.now() - (data.days - 1) * 86_400_000).toISOString().slice(0, 10)
      : (dates[0] ?? today);
    const empty = () => days(first, today).map((date) => ({ date, values: {}, total: 0 }) as Column);
    const tokenColumns = empty();
    const costColumns = empty();
    const index = new Map(tokenColumns.map((column, i) => [column.date, i]));
    for (const row of data.by_day) {
      const at = index.get(row.date);
      if (at === undefined) continue;
      const key = keyOf(row.model);
      tokenColumns[at].values[key] = (tokenColumns[at].values[key] ?? 0) + row.tokens;
      tokenColumns[at].total += row.tokens;
      costColumns[at].values[key] = (costColumns[at].values[key] ?? 0) + row.cost_usd;
      costColumns[at].total += row.cost_usd;
    }
    return { series, tokenColumns, costColumns };
  }, [data]);

  const total = data?.total;
  const unpricedModels = (data?.by_model ?? []).filter((row) => row.unpriced_tokens > 0).map((row) => row.model);
  return (
    <>
      {result.error && <ErrorBanner message={result.error} />}
      {result.loading && !data ? (
        <Loading />
      ) : !data || !total || !view ? null : total.tokens === 0 ? (
        <section className="panel stats-empty">
          <h2>{t('За этот период токенов нет')}</h2>
          <p className="muted">{t('Статистика появится после первой сессии или чата.')}</p>
        </section>
      ) : (
        <>
          <section className="stats-tiles" aria-label={t('Итого')}>
            <article className="panel stats-tile">
              <span>{t('Токенов')}</span>
              <strong>{tokens(total.tokens)}</strong>
              <small className="muted">
                {t(
                  'вход {0} · кэш {1} · выход {2}',
                  tokens(total.input + total.cache_write),
                  tokens(total.cache_read),
                  tokens(total.output),
                )}
              </small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Стоило бы по API')}</span>
              <strong>
                {money(total.cost_usd)}
                {total.unpriced_tokens > 0 && <sup>*</sup>}
              </strong>
              <small className="muted">{t('по подписке — в рамках лимитов')}</small>
            </article>
            <article className="panel stats-tile">
              <span>{t('Сессий и чатов')}</span>
              <strong>{total.sessions}</strong>
              <small className="muted">{t('{0} прогонов', total.runs)}</small>
            </article>
          </section>
          {total.unpriced_tokens > 0 && (
            <p className="stats-note muted">
              *{' '}
              {t(
                'Без цены {0} токенов ({1}): движок не сообщает стоимость. Задайте цены в',
                tokens(total.unpriced_tokens),
                unpricedModels.join(', '),
              )}{' '}
              <Link to="/settings/system">{t('настройках')}</Link>.
            </p>
          )}
          <Legend series={view.series} />
          <div className="stats-charts">
            <DailyChart title={t('Токены по дням')} columns={view.tokenColumns} series={view.series} format={tokens} />
            <DailyChart
              title={t('Стоимость по API по дням')}
              columns={view.costColumns}
              series={view.series}
              format={money}
            />
          </div>
          <UsageTable
            tabs={
              <div className="stats-periods" role="tablist" aria-label={t('Разрез')}>
                {TABLES.map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    className={table === value ? 'active' : ''}
                    aria-selected={table === value}
                    onClick={() => setTable(value)}
                  >
                    {t(label)}
                  </button>
                ))}
              </div>
            }
            rows={
              table === 'model'
                ? data.by_model.map((row) => ({ ...row, key: `${row.engine}/${row.model}`, label: row.model }))
                : table === 'account'
                  ? data.by_account.map((row) => ({ ...row, key: row.account_id ?? '', label: row.name }))
                  : data.by_project.map((row) => ({ ...row, key: row.project_id ?? '', label: row.project_id ?? '—' }))
            }
            link={table === 'project' ? (row) => (row.key ? `/projects/${row.key}` : null) : undefined}
          />
        </>
      )}
    </>
  );
}

export function Stats(): JSX.Element {
  const [tab, setTab] = useState<'usage' | 'efficiency'>('usage');
  const [period, setPeriod] = useState<number>(30);
  return (
    <div className="stats-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('РАБОЧЕЕ ПРОСТРАНСТВО')}</p>
          <h1>{t('Статистика')}</h1>
          <p className="muted">
            {tab === 'usage'
              ? t('Токены агентов и чатов по моделям и сколько это стоило бы по API.')
              : t('Во что обходятся задачи: токены, стоимость и время на задачу, оркестратор и исполнители.')}
          </p>
        </div>
        <div className="stats-heading-controls">
          <div className="stats-periods" role="tablist" aria-label={t('Раздел статистики')}>
            {(
              [
                ['usage', 'Расход'],
                ['efficiency', 'Эффективность'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                className={tab === value ? 'active' : ''}
                onClick={() => setTab(value)}
              >
                {t(label)}
              </button>
            ))}
          </div>
          <div className="stats-periods" role="group" aria-label={t('Период')}>
            {PERIODS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={period === value ? 'active' : ''}
                aria-pressed={period === value}
                onClick={() => setPeriod(value)}
              >
                {t(label)}
              </button>
            ))}
          </div>
        </div>
      </div>
      {tab === 'usage' ? <UsageStats period={period} /> : <Efficiency days={period} />}
    </div>
  );
}
