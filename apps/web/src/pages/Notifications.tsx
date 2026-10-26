import { useState } from 'react';
import { api } from '../api/client';
import type { Notification } from '../api/types';
import { ago, useApi } from '../api/useApi';
import { Link } from 'react-router-dom';
import { EmptyState, ErrorBanner, Loading, StatusBadge, Toolbar } from '../components/ui';
import { t } from '../i18n';

export function Notifications(): JSX.Element {
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('');
  const query = new URLSearchParams();
  if (category) query.set('category', category);
  if (severity) query.set('severity', severity);
  const data = useApi<Notification[]>(`/notifications?${query}`, { refreshMs: 15_000 });
  const markRead = async (item: Notification) => {
    await api(`/notifications/${item.id}/read`, { method: 'POST' });
  };
  const markAllRead = async () => {
    await api('/notifications/read-all', { method: 'POST' });
  };
  // The same count as the bell, not just the rows on screen (the list is limited).
  const unreadList = useApi<Notification[]>('/notifications?unread=true', { refreshMs: 15_000 });
  const unread = unreadList.data?.length ?? (data.data ?? []).filter((item) => !item.read_at).length;
  const categories = [...new Set((data.data ?? []).map((item) => item.category))];
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ЦЕНТР УВЕДОМЛЕНИЙ')}</p>
          <h1>{t('Уведомления')}</h1>
        </div>
        <div className="session-actions">
          <button className="button-secondary" onClick={() => void markAllRead()} disabled={!unread}>
            {t('Отметить все прочитанными')}
          </button>
          <button className="button-secondary" onClick={data.reload}>
            {t('Обновить')}
          </button>
        </div>
      </div>
      <Toolbar>
        <label>
          {t('Категория')}
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">{t('все')}</option>
            {categories.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          {t('Важность')}
          <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
            <option value="">{t('все')}</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="critical">critical</option>
          </select>
        </label>
      </Toolbar>
      <section className="panel">
        {data.error && <ErrorBanner message={data.error} />}
        {data.loading && !data.data ? (
          <Loading />
        ) : !data.data?.length ? (
          <EmptyState>{t('Уведомлений нет.')}</EmptyState>
        ) : (
          <ul className="notification-list">
            {data.data.map((item) => (
              <li className={item.read_at ? 'read' : ''} key={item.id}>
                <div>
                  <div className="event-meta">
                    <StatusBadge value={item.severity} />
                    <strong>{item.title}</strong>
                    <time>{ago(item.created_at)}</time>
                  </div>
                  <p>{item.body}</p>
                  {item.project_id && (
                    <small className="muted">
                      {t('Проект:')} {item.project_id}
                    </small>
                  )}
                  {item.link ? (
                    <Link to={item.link}>{t('Открыть связанный объект')}</Link>
                  ) : item.session_id ? (
                    <Link to={`/sessions/${item.session_id}`}>{t('Открыть связанную сессию')}</Link>
                  ) : item.project_id ? (
                    <Link to={`/projects/${item.project_id}`}>{t('Открыть связанный проект')}</Link>
                  ) : null}
                </div>
                {!item.read_at && (
                  <button className="button-secondary" onClick={() => void markRead(item)}>
                    {t('Прочитано')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
