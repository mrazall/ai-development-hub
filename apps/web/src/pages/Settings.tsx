import { FormEvent, useState } from 'react';
import { api } from '../api/client';
import { errorText, useApi } from '../api/useApi';
import type { User } from '../auth/session';
import { ErrorBanner, Loading, StatusBadge } from '../components/ui';
import { Link } from 'react-router-dom';
import { ThemeToggle } from '../components/ui';
import { t } from '../i18n';

type Health = { status: string; api_version: string; schema_version: number };
type UserRow = { id: string; username: string; role: string; created_at: string };

export function Settings({ user }: { user: User }): JSX.Element {
  const health = useApi<Health>('/health');
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('СИСТЕМА')}</p>
          <h1>{t('Настройки')}</h1>
        </div>
      </div>
      <div className="detail-grid">
        <section className="panel settings-links">
          <h2>{t('Разделы настроек')}</h2>
          <Link to="/settings/projects">{t('Проекты')}</Link>
          <Link to="/settings/workers">{t('Исполнители')}</Link>
          <Link to="/settings/sessions">{t('Сессии')}</Link>
          <Link to="/settings/accounts">{t('Аккаунты и модели')}</Link>
          <Link to="/settings/mcp">MCP</Link>
          <Link to="/backups">{t('Резервные копии')}</Link>
          {user.role === 'admin' && <Link to="/settings/users">{t('Пользователи')}</Link>}
        </section>
        <section className="panel">
          <h2>{t('Профиль')}</h2>
          <ThemeToggle />
          <dl>
            <dt>{t('Пользователь')}</dt>
            <dd>{user.username}</dd>
            <dt>{t('Роль')}</dt>
            <dd>
              <StatusBadge value={user.role} />
            </dd>
            <dt>API</dt>
            <dd>
              {health.loading
                ? t('проверка…')
                : health.error
                  ? t('недоступен')
                  : health.data
                    ? t('v{0}, схема {1}', health.data.api_version, health.data.schema_version)
                    : t('неизвестно')}
            </dd>
          </dl>
        </section>
        {user.role === 'admin' && <Users />}
      </div>
    </>
  );
}

function Users(): JSX.Element {
  const users = useApi<UserRow[]>('/users');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('viewer');
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api('/users', { method: 'POST', body: JSON.stringify({ username, password, role }) });
      setUsername('');
      setPassword('');
      setError('');
      users.reload();
    } catch (cause) {
      setError(errorText(cause, t('Не удалось создать пользователя')));
    }
  };

  return (
    <section className="panel">
      <h2>{t('Пользователи')}</h2>
      {users.error && <ErrorBanner message={users.error} />}
      {!users.data ? (
        <Loading />
      ) : (
        <ul className="row-list">
          {users.data.map((row) => (
            <li key={row.id}>
              <span>{row.username}</span>
              <StatusBadge value={row.role} />
            </li>
          ))}
        </ul>
      )}
      <form className="create-form" onSubmit={submit}>
        <h3>{t('Новый пользователь')}</h3>
        <label>
          {t('Имя')}
          <input value={username} onChange={(event) => setUsername(event.target.value)} required autoComplete="off" />
        </label>
        <label>
          {t('Пароль')}
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={12}
            required
            autoComplete="new-password"
          />
        </label>
        <label>
          {t('Роль')}
          <select value={role} onChange={(event) => setRole(event.target.value)}>
            <option value="viewer">{t('viewer — только чтение')}</option>
            <option value="admin">admin</option>
          </select>
        </label>
        {error && <ErrorBanner message={error} />}
        <button disabled={!username.trim() || password.length < 12}>{t('Создать')}</button>
      </form>
    </section>
  );
}
