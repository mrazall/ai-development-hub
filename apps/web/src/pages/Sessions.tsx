import { DeleteSessionButton } from '../components/DeleteSessionButton';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Project, Session } from '../api/types';
import { sessionStatuses } from '../api/types';
import { ago, useApi } from '../api/useApi';
import { EmptyState, ErrorBanner, Input, Loading, StatusBadge, Table, Toolbar } from '../components/ui';
import { t } from '../i18n';

export function Sessions(): JSX.Element {
  const [params, setParams] = useSearchParams();
  const project = params.get('project') ?? '';
  const status = params.get('status') ?? '';
  const [queryText, setQueryText] = useState('');
  const [sort, setSort] = useState<'updated' | 'project' | 'status'>('updated');
  const query = new URLSearchParams();
  if (project) query.set('project_id', project);
  if (status) query.set('status', status);
  const sessions = useApi<Session[]>(`/sessions?${query.toString()}`);
  const projects = useApi<Project[]>('/projects');
  const visible = useMemo(() => {
    const queryTextNormalized = queryText.trim().toLowerCase();
    return (sessions.data ?? [])
      .filter((session) =>
        `${session.id} ${session.project_id} ${session.engine} ${session.model} ${session.worker_id}`
          .toLowerCase()
          .includes(queryTextNormalized),
      )
      .sort((left, right) => {
        if (sort === 'project') return left.project_id.localeCompare(right.project_id);
        if (sort === 'status') return left.status.localeCompare(right.status);
        return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
      });
  }, [sessions.data, queryText, sort]);

  const select = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('АГЕНТЫ')}</p>
          <h1>{t('Сессии')}</h1>
        </div>
        <button className="button-secondary" onClick={sessions.reload}>
          {t('Обновить')}
        </button>
      </div>
      <Toolbar>
        <label>
          {t('Проект')}
          <select value={project} onChange={(event) => select('project', event.target.value)}>
            <option value="">{t('все')}</option>
            {(projects.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="toolbar-search">
          {t('Поиск')}
          <Input
            value={queryText}
            onChange={(event) => setQueryText(event.target.value)}
            placeholder={t('Проект, модель, worker…')}
          />
        </label>
        <label>
          {t('Сортировка')}
          <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
            <option value="updated">{t('сначала новые')}</option>
            <option value="project">{t('по проекту')}</option>
            <option value="status">{t('по статусу')}</option>
          </select>
        </label>
        <label>
          {t('Статус')}
          <select value={status} onChange={(event) => select('status', event.target.value)}>
            <option value="">{t('все')}</option>
            {sessionStatuses.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </label>
      </Toolbar>
      <section className="panel">
        {sessions.error && <ErrorBanner message={sessions.error} />}
        {sessions.loading && !sessions.data ? (
          <Loading />
        ) : !visible.length ? (
          <EmptyState>{t('Сессий нет. Агентов запускает Stage 3 — сейчас сессии создаются через API.')}</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>{t('Сессия')}</th>
                <th>{t('Агент / модель')}</th>
                <th>Worker</th>
                <th>{t('Статус')}</th>
                <th>{t('Обновлена')}</th>
                <th aria-label={t('Действия')} />
              </tr>
            </thead>
            <tbody>
              {visible.map((session) => (
                <tr key={session.id}>
                  <td>
                    <Link to={`/sessions/${session.id}`}>{session.project_id}</Link>
                    <br />
                    <small className="muted">{session.branch ?? session.workdir}</small>
                  </td>
                  <td>
                    {session.engine}
                    <br />
                    <small className="muted">
                      {session.provider} · {session.model}
                    </small>
                  </td>
                  <td>{session.worker_id}</td>
                  <td>
                    <StatusBadge value={session.status} />
                  </td>
                  <td>{ago(session.updated_at)}</td>
                  <td>
                    <DeleteSessionButton session={session} onDeleted={sessions.reload} />
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>
    </>
  );
}
