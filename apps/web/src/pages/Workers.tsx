import { FormEvent, useState } from 'react';
import { api } from '../api/client';
import type { Worker } from '../api/types';
import { errorText, useApi } from '../api/useApi';
import type { User } from '../auth/session';
import { EmptyState, ErrorBanner, Loading, StatusBadge, Table } from '../components/ui';
import { t } from '../i18n';
import { TimeAgo } from '../components/time';

export function Workers({ user }: { user: User }): JSX.Element {
  const workers = useApi<Worker[]>('/workers');
  const [issued, setIssued] = useState<Worker | null>(null);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ИСПОЛНИТЕЛИ')}</p>
          <h1>{t('Исполнители')}</h1>
        </div>
        <button className="button-secondary" onClick={workers.reload}>
          {t('Обновить')}
        </button>
      </div>
      {issued?.worker_token && (
        <div className="notice" role="alert">
          <strong>
            {t('Токен worker «')}
            {issued.id}
            {t('» — показывается один раз.')}
          </strong>
          <p>
            {t('Сохраните его на машине worker. Сервер хранит только хэш; при потере зарегистрируйте worker заново.')}
          </p>
          <code className="secret">{issued.worker_token}</code>
          <button className="button-secondary" onClick={() => setIssued(null)}>
            {t('Я сохранил токен')}
          </button>
        </div>
      )}
      <div className="project-layout">
        <section className="panel">
          {workers.error && <ErrorBanner message={workers.error} />}
          {workers.loading && !workers.data ? (
            <Loading />
          ) : !workers.data?.length ? (
            <EmptyState>{t('Worker пока не зарегистрированы.')}</EmptyState>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>{t('Тип')}</th>
                  <th>{t('Метки')}</th>
                  <th>{t('Статус')}</th>
                  <th>Heartbeat</th>
                </tr>
              </thead>
              <tbody>
                {workers.data.map((worker) => (
                  <tr key={worker.id}>
                    <td>
                      <strong>{worker.id}</strong>
                      <br />
                      <small className="muted">{worker.host}</small>
                    </td>
                    <td>{worker.kind}</td>
                    <td>{worker.labels.join(', ') || '—'}</td>
                    <td>
                      <StatusBadge value={worker.status} />
                    </td>
                    <td title={worker.last_heartbeat_at ?? ''}>
                      <TimeAgo value={worker.last_heartbeat_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </section>
        {user.role === 'admin' && (
          <RegisterWorker
            onRegistered={(worker) => {
              setIssued(worker);
              workers.reload();
            }}
          />
        )}
      </div>
    </>
  );
}

function RegisterWorker({ onRegistered }: { onRegistered: (worker: Worker) => void }): JSX.Element {
  const [id, setId] = useState('');
  const [host, setHost] = useState('');
  const [kind, setKind] = useState<Worker['kind']>('ssh');
  const [labels, setLabels] = useState('');
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const worker = await api<Worker>('/workers', {
        method: 'POST',
        body: JSON.stringify({
          id,
          host,
          kind,
          labels: labels
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean),
        }),
      });
      setId('');
      setHost('');
      setLabels('');
      setError('');
      onRegistered(worker);
    } catch (cause) {
      setError(errorText(cause, t('Не удалось зарегистрировать worker')));
    }
  };

  return (
    <form className="panel create-form" onSubmit={submit}>
      <h2>{t('Регистрация worker')}</h2>
      <label>
        ID
        <input value={id} onChange={(event) => setId(event.target.value)} required placeholder="my-worker" />
      </label>
      <label>
        {t('Хост')}
        <input value={host} onChange={(event) => setHost(event.target.value)} required placeholder="my-pc" />
      </label>
      <label>
        {t('Тип')}
        <select value={kind} onChange={(event) => setKind(event.target.value as Worker['kind'])}>
          <option value="ssh">ssh</option>
          <option value="local">local</option>
          <option value="codeman">codeman</option>
        </select>
      </label>
      <label>
        {t('Метки')}
        <input value={labels} onChange={(event) => setLabels(event.target.value)} placeholder="gpu, wsl2" />
      </label>
      <small>{t('После регистрации будет показан токен worker — один раз.')}</small>
      {error && <ErrorBanner message={error} />}
      <button disabled={!id.trim() || !host.trim()}>{t('Зарегистрировать')}</button>
    </form>
  );
}
