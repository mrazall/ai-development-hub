import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { tokenKey } from '../auth/session';
import { ErrorBanner } from '../components/ui';
import { LogoMark } from '../components/Logo';
import { t } from '../i18n';

export function Login(): JSX.Element {
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const result = await api<{ access_token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: data.get('username'), password: data.get('password') }),
      });
      sessionStorage.setItem(tokenKey, result.access_token);
      navigate('/');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Не удалось войти'));
    }
  };
  return (
    <main className="auth">
      <form className="auth-card" onSubmit={submit}>
        <LogoMark size={48} className="auth-logo" />
        <p className="eyebrow">CONTROL PLANE</p>
        <h1>AI Development Hub</h1>
        <label>
          {t('Пользователь')}
          <input name="username" required autoComplete="username" />
        </label>
        <label>
          {t('Пароль')}
          <input name="password" type="password" required autoComplete="current-password" />
        </label>
        <button className="ui-button ui-button-primary" type="submit">
          {t('Войти')}
        </button>
        {error && <ErrorBanner message={error} />}
      </form>
    </main>
  );
}
