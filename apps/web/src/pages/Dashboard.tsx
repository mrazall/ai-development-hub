import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useEventStream } from '../api/events';
import { isPartial, isTechnical } from '../api/sessionFeed';
import type { SessionEvent } from '../api/types';
import { EmptyState, ErrorBanner, Loading, StatusBadge } from '../components/ui';
import { Link } from 'react-router-dom';
import type { LimitsResponse } from '../api/types-limits';
import { useApi } from '../api/useApi';
import { t } from '../i18n';

type Summary = {
  projects: number;
  tasks: Record<string, number>;
  workers: Record<string, number>;
  sessions: Record<string, number>;
  events: { cursor: number; kind: string; ts: string; payload: Record<string, unknown> }[];
  services: { api: string; database: string; knowledge: string };
};
const MEANINGFUL = new Set(['message', 'session.status', 'approval.request', 'diff']);
function eventLabel(event: Summary['events'][number]): string {
  if (event.kind === 'session.status') return t('Статус сессии: {0}', String(event.payload.status ?? '—'));
  const value = event.payload.text ?? event.payload.output;
  return typeof value === 'string' && value.trim() ? value : event.kind.replaceAll('.', ' · ');
}
function total(values: Record<string, number>): number {
  return Object.values(values).reduce((sum, value) => sum + value, 0);
}
export function Dashboard(): JSX.Element {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  const liveEvents = useEventStream();
  const limits = useApi<LimitsResponse>('/limits');
  useEffect(() => {
    void api<Summary>('/dashboard')
      .then(async (data) => {
        try {
          await api('/knowledge/health');
          setSummary({ ...data, services: { ...data.services, knowledge: 'ok' } });
        } catch {
          setSummary({ ...data, services: { ...data.services, knowledge: 'unavailable' } });
        }
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : t('Не удалось загрузить dashboard')));
  }, []);
  if (!summary)
    return (
      <>
        <h1>{t('Обзор')}</h1>
        {error ? <ErrorBanner message={error} /> : <Loading />}
      </>
    );
  // The live stream replays history on (re)connect: merge by cursor so nothing is shown twice.
  const byCursor = new Map(summary.events.map((event) => [event.cursor, event]));
  liveEvents.forEach((event) => byCursor.set(event.cursor, event));
  // Only what a person acts on: replies, status changes, approvals, file changes. Engine bookkeeping,
  // streamed partials and raw tool traffic stay in the session's Events tab; repeats collapse.
  const seen = new Set<string>();
  const events = [...byCursor.values()]
    .sort((a, b) => b.cursor - a.cursor)
    .filter((event) => {
      const asSession = event as unknown as SessionEvent;
      if (!MEANINGFUL.has(event.kind) || isPartial(asSession) || isTechnical(asSession)) return false;
      const key = `${event.kind}|${eventLabel(event)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 20);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ОБЗОР HUB')}</p>
          <h1>{t('Обзор')}</h1>
        </div>
        <StatusBadge value={summary.services.api} />
      </div>
      {error && <ErrorBanner message={error} />}
      <section className="stats-grid" aria-label={t('Ключевые показатели')}>
        <article className="stat-card">
          <span>{t('Проекты')}</span>
          <strong>{summary.projects}</strong>
        </article>
        <article className="stat-card">
          <span>{t('Исполнители')}</span>
          <strong>
            {summary.workers.online ?? 0} <small>{t('в сети')}</small>
          </strong>
          <p>{summary.workers.offline ?? 0} offline</p>
        </article>
        <article className="stat-card">
          <span>{t('Сессии')}</span>
          <strong>{summary.sessions.running ?? 0}</strong>
          <p>{t('активных')}</p>
        </article>
        <article className="stat-card">
          <span>{t('Задачи')}</span>
          <strong>{Object.values(summary.tasks).reduce((total, count) => total + count, 0)}</strong>
          <p>
            {summary.tasks.done ?? 0} {t('завершено')}
          </p>
        </article>
      </section>
      <section className="dashboard-strip" aria-label={t('Текущее выполнение')}>
        <article className="panel dashboard-focus-card">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t('СЕЙЧАС')}</p>
              <h2>{t('Живые сессии')}</h2>
            </div>
            <StatusBadge value={summary.sessions.running ? 'running' : 'completed'} />
          </div>
          {summary.sessions.running ? (
            <Link className="dashboard-link" to="/sessions">
              {summary.sessions.running} {t('активных сессий · Открыть')}
            </Link>
          ) : (
            <EmptyState
              title={t('Нет активных сессий')}
              action={
                <Link className="ui-button ui-button-primary" to="/workspace">
                  {t('Запустить сессию')}
                </Link>
              }
            >
              {t('Новая рабочая задача появится здесь.')}
            </EmptyState>
          )}
        </article>
        <article className="panel dashboard-focus-card">
          <p className="eyebrow">{t('ВНИМАНИЕ')}</p>
          <h2>{t('Ожидают подтверждения')}</h2>
          {(summary.sessions.waiting_approval ?? 0) ? (
            <Link className="dashboard-link" to="/notifications">
              {summary.sessions.waiting_approval} {t('запроса · Проверить')}
            </Link>
          ) : (
            <p className="muted">{t('Всё согласовано.')}</p>
          )}
        </article>
        <article className="panel dashboard-focus-card">
          <p className="eyebrow">WORKERS</p>
          <h2>{t('Онлайн')}</h2>
          {summary.workers.online ? (
            <Link className="dashboard-link" to="/settings/workers">
              {summary.workers.online} {t('worker-ов доступны')}
            </Link>
          ) : (
            <EmptyState
              title={t('Нет worker-ов онлайн')}
              action={
                <Link className="ui-button ui-button-secondary" to="/settings/workers">
                  {t('Настроить worker')}
                </Link>
              }
            />
          )}
        </article>
        <LimitWidget data={limits.data} />
      </section>
      <div className="dashboard-columns">
        <section className="panel dashboard-services">
          <h2>{t('Состояние сервисов')}</h2>
          <div className="service-list">
            {Object.entries(summary.services).map(([name, value]) => (
              <div key={name}>
                <span>{name}</span>
                <StatusBadge value={value} />
              </div>
            ))}
          </div>
        </section>
        <section className="panel dashboard-tasks">
          <div className="panel-heading">
            <h2>{t('Задачи по статусам')}</h2>
            <strong>{total(summary.tasks)}</strong>
          </div>
          {Object.entries(summary.tasks).map(([status, count]) => (
            <div className="meter-row" key={status}>
              <span>{status}</span>
              <b>{count}</b>
            </div>
          ))}
        </section>
        <section className="panel dashboard-events">
          <div className="panel-heading">
            <h2>{t('Последние события')}</h2>
            <span className="live-dot">LIVE</span>
          </div>
          {events.length === 0 ? (
            <p className="muted">{t('Событий пока нет.')}</p>
          ) : (
            <ul className="event-list">
              {events.map((event) => (
                <li key={event.cursor}>
                  <StatusBadge value={event.kind} />
                  <span title={eventLabel(event)}>{eventLabel(event)}</span>
                  <time>{new Date(event.ts).toLocaleTimeString()}</time>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function LimitWidget({ data }: { data: LimitsResponse | null }): JSX.Element {
  const accounts = Array.isArray(data) ? data : (data?.accounts ?? data?.limits ?? []);
  const hottest = accounts
    .flatMap((account) => account.windows.map((window) => ({ account, window })))
    .sort((a, b) => b.window.used_percent - a.window.used_percent)[0];
  return (
    <article className="panel dashboard-focus-card dashboard-limit-widget">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t('ЛИМИТЫ')}</p>
          <h2>{t('Самое загруженное окно')}</h2>
        </div>
      </div>
      {hottest ? (
        <Link className="dashboard-link" to="/limits">
          {hottest.account.account_name || hottest.account.account_id} · {Math.round(hottest.window.used_percent)}%
        </Link>
      ) : (
        <Link className="dashboard-link" to="/limits">
          {t('Лимиты появятся после первой сессии')}
        </Link>
      )}
    </article>
  );
}
