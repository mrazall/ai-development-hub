import { NavLink } from 'react-router-dom';
import { useState } from 'react';
import { Icon, type IconName } from './ui/icons';
import { t } from '../i18n';

const links = [
  ['/chats', t('Чаты'), 'chats'],
  ['/workspace', t('Рабочая область'), 'workspace'],
  ['/projects', t('Проекты'), 'projects'],
  ['/tasks', t('Задачи'), 'tasks'],
  ['/agents', t('Агенты'), 'agents'],
  ['/knowledge', t('Знания'), 'knowledge'],
  ['/knowledge/drafts', t('Черновики агентов'), 'drafts'],
  ['/notifications', t('Уведомления'), 'notifications'],
] as const;
const settings = [
  ['/settings', t('Настройки')],
  ['/settings/projects', t('Проекты')],
  ['/settings/workers', t('Исполнители')],
  ['/settings/sessions', t('Сессии')],
  ['/settings/accounts', t('Аккаунты и модели')],
  ['/settings/mcp', 'MCP'],
  ['/settings/users', t('Пользователи')],
  ['/settings/system', t('Система')],
];
export function NavBar(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const closeMenu = () => {
    setOpen(false);
    setSettingsOpen(false);
  };
  return (
    <nav className="nav" aria-label={t('Основная навигация')}>
      <button
        className="nav-toggle"
        aria-expanded={open}
        aria-controls="mobile-navigation"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? t('Закрыть меню') : t('Меню')}
      </button>
      <div className={`nav-links ${open ? 'open' : ''}`} id="mobile-navigation">
        <span className="nav-group-label">{t('РАБОЧЕЕ ПРОСТРАНСТВО')}</span>
        {links.map(([path, label, icon]) => (
          <NavLink key={path} to={path} end={path === '/knowledge'} onClick={closeMenu}>
            <span className="nav-icon" aria-hidden="true">
              <Icon name={icon as IconName} />
            </span>
            <span>{label}</span>
          </NavLink>
        ))}
        <span className="nav-group-label">{t('СИСТЕМА')}</span>
        <NavLink to="/health" onClick={closeMenu}>
          <span className="nav-icon" aria-hidden="true">
            <Icon name="health" />
          </span>
          <span>{t('Здоровье системы')}</span>
        </NavLink>
        <NavLink to="/backups" onClick={closeMenu}>
          <span className="nav-icon" aria-hidden="true">
            <Icon name="backups" />
          </span>
          <span>{t('Резервные копии')}</span>
        </NavLink>
        <NavLink to="/limits" onClick={closeMenu}>
          <span className="nav-icon" aria-hidden="true">
            <Icon name="limits" />
          </span>
          <span>{t('Лимиты')}</span>
        </NavLink>
        <span className="nav-settings">
          <NavLink to="/settings" onClick={closeMenu}>
            <span className="nav-icon" aria-hidden="true">
              <Icon name="settings" />
            </span>
            {t('Настройки')}
          </NavLink>
          <button className="nav-more" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}>
            {t('Ещё')}
          </button>
          {settingsOpen && (
            <span className="nav-menu">
              {settings.slice(1).map(([path, label]) => (
                <NavLink key={path} to={path} onClick={closeMenu}>
                  {label}
                </NavLink>
              ))}
            </span>
          )}
        </span>
      </div>
    </nav>
  );
}
