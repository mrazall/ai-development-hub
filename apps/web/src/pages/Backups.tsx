import { ago, useApi } from '../api/useApi';
import { ErrorBanner, Loading, StatusBadge } from '../components/ui';
import { t } from '../i18n';
import { TimeAgo } from '../components/time';

type Snapshot = {
  id: string;
  kind: string;
  created_at?: string;
  completed_at?: string;
  finished_at?: string;
  size_bytes?: number | null;
  ok?: boolean;
  error?: string | null;
  restore_test_ok?: boolean | null;
};
type Status = { kind?: string; last_success_at?: string | null; rpo_exceeded?: boolean };
type StatusResponse = Status[] | { statuses?: Status[]; items?: Status[] } | Status;
type Response = Snapshot[] | { snapshots?: Snapshot[]; items?: Snapshot[] };

const labels: Record<string, string> = {
  database: t('База данных'),
  config: t('Конфигурация'),
  vault: 'Vault',
  restore_test: t('Тест восстановления'),
};
const timeOf = (s?: Snapshot): string | null => s?.completed_at ?? s?.finished_at ?? s?.created_at ?? null;
const itemsOf = (r: Response | null): Snapshot[] => (Array.isArray(r) ? r : (r?.snapshots ?? r?.items ?? []));
const statusesOf = (r: StatusResponse | null): Status[] => {
  if (!r) return [];
  if (Array.isArray(r)) return r;
  if ('statuses' in r) return r.statuses ?? [];
  if ('items' in r) return r.items ?? [];
  return [r as Status];
};
function sizeOf(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value < 1024) return t('{0} Б', value);
  if (value < 1024 ** 2) return t('{0} КБ', (value / 1024).toFixed(1));
  if (value < 1024 ** 3) return t('{0} МБ', (value / 1024 ** 2).toFixed(1));
  return t('{0} ГБ', (value / 1024 ** 3).toFixed(1));
}

export function Backups(): JSX.Element {
  const list = useApi<Response>('/backups');
  const status = useApi<StatusResponse>('/backups/status');
  const missing = list.error.includes('(404)') || status.error.includes('(404)');
  const latest = new Map<string, Snapshot>();
  itemsOf(list.data).forEach((item) => {
    const old = latest.get(item.kind);
    if (!old || (timeOf(item) ?? '') > (timeOf(old) ?? '')) latest.set(item.kind, item);
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('НАДЁЖНОСТЬ')}</p>
          <h1>{t('Резервные копии')}</h1>
          <p className="muted">{t('Снимки PostgreSQL и конфигурации хаба с контролем RPO.')}</p>
        </div>
      </div>
      {missing && (
        <div className="notice" role="status">
          <strong>{t('API резервных копий пока недоступен')}</strong>
          <span>{t('Запуск — по расписанию на сервере. Когда API появится, последние снимки отобразятся здесь.')}</span>
        </div>
      )}
      {list.error && !missing && <ErrorBanner message={list.error} />}
      {status.error && !missing && <ErrorBanner message={status.error} />}
      {!list.data && list.loading ? (
        <Loading />
      ) : (
        <>
          <section className="backup-grid" aria-label={t('Последние резервные копии')}>
            {['database', 'config', 'vault', 'restore_test'].map((kind) => (
              <BackupCard key={kind} kind={kind} snapshot={latest.get(kind)} />
            ))}
          </section>
          {!!statusesOf(status.data).length && (
            <section className="panel backup-status-panel">
              <div className="panel-heading">
                <h2>{t('Контроль RPO')}</h2>
                <span className="muted">{t('База данных: 6 ч')}</span>
              </div>
              <div className="backup-status-list">
                {statusesOf(status.data).map((item) => (
                  <div className="backup-status-row" key={item.kind ?? 'database'}>
                    <strong>{labels[item.kind ?? ''] ?? item.kind ?? t('Резервная копия')}</strong>
                    <span>
                      {item.last_success_at ? <TimeAgo value={item.last_success_at} /> : t('нет успешного снимка')}
                    </span>
                    <StatusBadge value={item.rpo_exceeded ? 'failed' : 'ok'} />
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}

function BackupCard({ kind, snapshot }: { kind: string; snapshot?: Snapshot }): JSX.Element {
  const ok = snapshot?.ok === true;
  return (
    <article className="panel backup-card">
      <div className="card-top">
        <h2>{labels[kind] ?? kind}</h2>
        {snapshot && <StatusBadge value={ok ? 'ok' : 'failed'} />}
      </div>
      <p className="backup-age">
        {snapshot?.error ? (
          <span className="backup-error">{snapshot.error}</span>
        ) : snapshot ? (
          timeOf(snapshot) ? (
            ago(timeOf(snapshot))
          ) : (
            t('время неизвестно')
          )
        ) : (
          t('Снимков ещё нет')
        )}
      </p>
      <dl>
        <dt>{t('Размер')}</dt>
        <dd>{sizeOf(snapshot?.size_bytes)}</dd>
        <dt>{t('Результат')}</dt>
        <dd>{snapshot ? (ok ? t('Успешно') : t('Ошибка')) : t('Снимка нет')}</dd>
        {kind === 'restore_test' && (
          <>
            <dt>{t('Проверка')}</dt>
            <dd>
              {snapshot?.restore_test_ok == null ? '—' : snapshot.restore_test_ok ? t('Пройдена') : t('Не пройдена')}
            </dd>
          </>
        )}
      </dl>
    </article>
  );
}
