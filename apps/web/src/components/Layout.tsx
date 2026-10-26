import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { useApi } from '../api/useApi';
import { useEventStream } from '../api/events';
import type { Approval, Notification } from '../api/types';
import { logout } from '../auth/session';
import { LogoMark } from './Logo';
import type { User } from '../auth/session';
import { NavBar } from './NavBar';
import { IconButton, LangToggle, ThemeToggle } from './ui';
import { Icon } from './ui/icons';
import { t } from '../i18n';

const commands = [
  ['/chats', t('Открыть чаты')],
  ['/workspace', t('Открыть рабочую область')],
  ['/projects', t('Открыть проекты')],
  ['/tasks', t('Открыть задачи')],
  ['/knowledge', t('Открыть знания')],
  ['/agents', t('Открыть граф агентов')],
  ['/settings', t('Открыть настройки')],
] as const;

export function Layout({ user }: { user: User }): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState('');
  const signOut = () => {
    logout();
    navigate('/login');
  };
  const unread = useApi<Notification[]>('/notifications?unread=true', { refreshMs: 15_000 });
  const info = useApi<{ demo: boolean }>('/system/info');
  const approvals = useApi<Approval[]>('/approvals?status=pending');
  const events = useEventStream({ limit: 20 });
  useEffect(() => {
    const timer = window.setInterval(unread.reload, 30_000);
    return () => window.clearInterval(timer);
  }, [unread.reload]);
  useEffect(() => {
    if (events.some((event) => event.kind === 'notification')) unread.reload();
  }, [events, unread.reload]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (location.pathname.startsWith('/chats')) {
          navigate('/chats');
          return;
        }
        setPalette(true);
      }
      if (event.key === 'Escape') setPalette(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [location.pathname, navigate]);
  const filteredCommands = useMemo(
    () => commands.filter(([, label]) => label.toLowerCase().includes(query.toLowerCase())),
    [query],
  );
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <Link to="/workspace" className="brand">
            <LogoMark size={28} className="brand-logo" />
            <span>AI Development Hub</span>
          </Link>
          <span className="breadcrumb">/ {location.pathname.split('/').filter(Boolean)[0] ?? t('обзор')}</span>
        </div>
        <button className="global-search" onClick={() => setPalette(true)} aria-label={t('Открыть палитру команд')}>
          <Icon name="search" size={16} />
          <span>{t('Перейти к странице…')}</span>
          <kbd>⌘ K</kbd>
        </button>
        <div className="topbar-actions">
          <Link className="notification-link" to="/notifications" aria-label={t('Уведомления')}>
            <Icon name="notifications" />
            {(unread.data?.length ?? 0) + (approvals.data?.length ?? 0) ? (
              <b>{(unread.data?.length ?? 0) + (approvals.data?.length ?? 0)}</b>
            ) : null}
          </Link>
          <LangToggle />
          <ThemeToggle />
          <span className="account-name">
            {user.username} · <b>{user.role}</b>
          </span>
          <IconButton label={t('Выйти')} className="button-secondary" onClick={signOut}>
            <Icon name="logout" />
          </IconButton>
        </div>
      </header>
      <NavBar />
      <main className="content">
        {info.data?.demo && (
          <div className="demo-banner" role="note">
            {t(
              'Демо-режим: агенты здесь — встроенные mock-движки, подписки Claude и Codex не нужны. Настоящие агенты подключаются через воркер на вашей машине.',
            )}
          </div>
        )}
        <Outlet />
      </main>
      {palette && (
        <div className="command-palette-backdrop" role="presentation" onMouseDown={() => setPalette(false)}>
          <div
            className="command-palette"
            role="dialog"
            aria-modal="true"
            aria-label={t('Палитра команд')}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('Поиск страниц…')}
              aria-label={t('Поиск команд')}
            />
            {filteredCommands.map(([path, label]) => (
              <button
                key={path}
                className="command-item"
                onClick={() => {
                  navigate(path);
                  setPalette(false);
                  setQuery('');
                }}
              >
                <span>{label}</span>
                <kbd>{path}</kbd>
              </button>
            ))}
            {!filteredCommands.length && <p className="muted">{t('Ничего не найдено.')}</p>}
            <small className="muted">{t('Esc — закрыть')}</small>
          </div>
        </div>
      )}
    </div>
  );
}
