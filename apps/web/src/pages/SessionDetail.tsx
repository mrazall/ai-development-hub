import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { eventKinds, useEventStream } from '../api/events';
import type { StreamEvent } from '../api/events';
import type { Session, WorkerDetails } from '../api/types';
import { useApi } from '../api/useApi';
import { ErrorBanner, Loading, StatusBadge, sessionStatus } from '../components/ui';
import { SessionTerminal } from '../components/Terminal';
import { t } from '../i18n';
import { TimeAgo } from '../components/time';

// ТЗ, раздел 4: показывать источник статуса и не изображать непроверенный ход мыслей модели.
const sourceLabel: Record<Session['status_source'], string> = {
  native: t('нативные события движка'),
  cli_parser: t('разбор вывода CLI'),
  heartbeat: t('только heartbeat'),
};

export function SessionDetail(): JSX.Element {
  const { id = '' } = useParams();
  const session = useApi<Session>(`/sessions/${id}`);
  const history = useApi<StreamEvent[]>(`/events?session_id=${encodeURIComponent(id)}&limit=500`);
  const worker = useApi<WorkerDetails>(session.data ? `/workers/${encodeURIComponent(session.data.worker_id)}` : null);
  const live = useEventStream({ sessionId: id, limit: 500 });
  const [kind, setKind] = useState('');

  if (session.error)
    return (
      <>
        <BackLink />
        <ErrorBanner message={session.error} />
      </>
    );
  if (!session.data)
    return (
      <>
        <BackLink />
        <Loading />
      </>
    );
  const data = session.data;

  // History first, then live events; the cursor deduplicates the overlap after (re)connects.
  const byCursor = new Map<number, StreamEvent>();
  [...(history.data ?? []), ...live].forEach((event) => byCursor.set(event.cursor, event));
  const events = [...byCursor.values()]
    .sort((a, b) => a.cursor - b.cursor)
    .filter((event) => !kind || event.kind === kind);

  return (
    <>
      <BackLink />
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('СЕССИЯ')}</p>
          <h1>
            {data.project_id} · {data.engine}
          </h1>
          <p className="muted">{data.id}</p>
        </div>
        <StatusBadge value={sessionStatus(data)} />
      </div>
      <p>
        <Link className="button-secondary" to={`/sessions/${data.id}/files`}>
          {t('Файлы и diff worker')}
        </Link>
      </p>
      <TerminalPanel session={data} worker={worker.data} workerError={worker.error} />
      <div className="detail-grid">
        <section className="panel">
          <dl>
            <dt>{t('Агент')}</dt>
            <dd>{data.engine}</dd>
            <dt>{t('Провайдер / модель')}</dt>
            <dd>
              {data.provider} · {data.model}
            </dd>
            <dt>{t('Авторизация')}</dt>
            <dd>{data.auth_mode}</dd>
            <dt>Worker</dt>
            <dd>{data.worker_id}</dd>
            <dt>{t('Каталог')}</dt>
            <dd>
              <code>{data.workdir}</code>
            </dd>
            <dt>{t('Ветка')}</dt>
            <dd>{data.branch ?? '—'}</dd>
            <dt>{t('Источник статуса')}</dt>
            <dd>{sourceLabel[data.status_source] ?? data.status_source}</dd>
            <dt>{t('Обновлена')}</dt>
            <dd>
              <TimeAgo value={data.updated_at} />
            </dd>
          </dl>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>{t('События')}</h2>
            <label className="inline">
              {t('Тип')}
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                <option value="">{t('все')}</option>
                {eventKinds.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <span className="live-dot">LIVE</span>
          </div>
          {history.error && <ErrorBanner message={history.error} />}
          {events.length === 0 ? (
            <p className="muted">{t('Событий пока нет.')}</p>
          ) : (
            <ol className="event-log" aria-label={t('Журнал событий сессии')}>
              {events.map((event) => (
                <EventRow key={event.cursor} event={event} />
              ))}
            </ol>
          )}
        </section>
      </div>
    </>
  );
}

function TerminalPanel({
  session,
  worker,
  workerError,
}: {
  session: Session;
  worker?: WorkerDetails | null;
  workerError: string;
}): JSX.Element {
  const iframeUrl =
    session.workspace_ref && worker?.workspace_url
      ? `${worker.workspace_url.replace(/\/$/, '')}/sessions/${encodeURIComponent(session.workspace_ref)}`
      : '';
  return (
    <section className="panel terminal-panel" aria-label={t('Терминал сессии')}>
      {iframeUrl && (
        <a className="button-secondary" href={iframeUrl} target="_blank" rel="noreferrer">
          {t('Открыть в Codeman')}
        </a>
      )}
      {workerError && (
        <p className="muted">
          {t('Адрес worker недоступен:')} {workerError}
        </p>
      )}
      <SessionTerminal sessionId={session.id} />
    </section>
  );
}

function EventRow({ event }: { event: StreamEvent }): JSX.Element {
  const output = event.kind === 'output' && typeof event.payload.text === 'string' ? event.payload.text : null;
  return (
    <li>
      <div className="event-meta">
        <StatusBadge value={event.kind} />
        <small className="muted">
          #{event.cursor} · {event.source}
          {event.redacted ? t(' · секреты скрыты') : ''}
        </small>
        <time>{new Date(event.ts).toLocaleTimeString()}</time>
      </div>
      <pre>{output ?? JSON.stringify(event.payload, null, 2)}</pre>
    </li>
  );
}

function BackLink(): JSX.Element {
  return (
    <Link className="back-link" to="/sessions">
      ← Sessions
    </Link>
  );
}
