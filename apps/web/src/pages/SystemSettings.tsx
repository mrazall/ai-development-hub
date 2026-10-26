import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { ago, useApi } from '../api/useApi';
import { ErrorBanner, Loading } from '../components/ui';
import { t } from '../i18n';

type Setting = {
  key: string;
  kind: 'text' | 'textarea' | 'url' | 'choice' | 'int';
  group: string;
  label: string;
  help: string;
  choices: string[] | null;
  value: string | number;
  default: string | number;
  source: 'env' | 'panel';
  updated_by: string | null;
  updated_at: string | null;
};

export function SystemSettings(): JSX.Element {
  const list = useApi<Setting[]>('/system/settings');
  const groups = [...new Set((list.data ?? []).map((item) => item.group))];
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('НАСТРОЙКИ')}</p>
          <h1>{t('Система')}</h1>
          <p className="muted">
            {t(
              'Значения по умолчанию задаются при развёртывании (переменные окружения). Изменённое здесь действует сразу и перекрывает их, пока не сбросите. Подключение к базе, секреты, политика безопасности и сокет Tailscale меняются только при развёртывании.',
            )}
          </p>
        </div>
      </div>
      {list.error && <ErrorBanner message={list.error} />}
      {list.loading && !list.data ? (
        <Loading />
      ) : (
        groups.map((group) => (
          <section className="panel settings-group" key={group}>
            <h2>{t(group)}</h2>
            {(list.data ?? [])
              .filter((item) => item.group === group)
              .map((item) => (
                <SettingRow key={item.key} setting={item} onSaved={list.reload} />
              ))}
          </section>
        ))
      )}
    </>
  );
}

function SettingRow({ setting, onSaved }: { setting: Setting; onSaved: () => void }): JSX.Element {
  const [value, setValue] = useState(String(setting.value ?? ''));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(String(setting.value ?? '')), [setting.value]);
  const dirty = value !== String(setting.value ?? '');
  const call = async (method: 'PUT' | 'DELETE') => {
    setBusy(true);
    setError('');
    try {
      await api(`/system/settings/${setting.key}`, {
        method,
        body: method === 'PUT' ? JSON.stringify({ value: setting.kind === 'int' ? Number(value) : value }) : undefined,
      });
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? t(cause.message) : t('Не сохранилось'));
    } finally {
      setBusy(false);
    }
  };
  const id = `setting-${setting.key}`;
  return (
    <div className="setting-row">
      <label htmlFor={id}>
        <strong>{t(setting.label)}</strong>
        <small className="muted">{t(setting.help)}</small>
      </label>
      {setting.kind === 'textarea' ? (
        <textarea id={id} rows={4} value={value} onChange={(event) => setValue(event.target.value)} />
      ) : setting.kind === 'choice' ? (
        <select id={id} value={value} onChange={(event) => setValue(event.target.value)}>
          {(setting.choices ?? []).map((choice) => (
            <option key={choice}>{choice}</option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          type={setting.kind === 'int' ? 'number' : setting.kind === 'url' ? 'url' : 'text'}
          min={setting.kind === 'int' ? 0 : undefined}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      )}
      <div className="setting-meta">
        <small className="muted">
          {setting.source === 'panel'
            ? t(
                'изменено в панели{0}{1} · по умолчанию: {2}',
                setting.updated_by ? `: ${setting.updated_by}` : '',
                setting.updated_at ? `, ${ago(setting.updated_at)}` : '',
                String(setting.default) || '—',
              )
            : t('значение из развёртывания')}
        </small>
        <span className="setting-actions">
          {setting.source === 'panel' && (
            <button className="button-secondary" disabled={busy} onClick={() => void call('DELETE')}>
              {t('Вернуть по умолчанию')}
            </button>
          )}
          <button disabled={busy || !dirty} onClick={() => void call('PUT')}>
            {t('Сохранить')}
          </button>
        </span>
      </div>
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
