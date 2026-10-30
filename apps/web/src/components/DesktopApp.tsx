import { FormEvent, useEffect, useState } from 'react';
import { t } from '../i18n';

// Inside the Windows app the panel can call the app's commands (the app grants this hub's origin); in a
// browser there is no bridge and the block is not shown.
type Invoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
const bridge = (window as unknown as { __TAURI_INTERNALS__?: { invoke: Invoke } }).__TAURI_INTERNALS__;
export const inDesktopApp = Boolean(bridge?.invoke);
export const call: Invoke = (command, args) => bridge!.invoke(command, args);

type AppStatus = { hubReachable: boolean; workerState: string; activeAgents: number; warning?: string | null };
type AppSettings = { autostart: boolean; workerId?: string | null };
type Failure = { code?: string; message?: string };

const failureText = (cause: unknown) => {
  const failure = cause as Failure;
  return failure?.message ?? String(cause);
};

/** The desktop app's own settings, in the panel's settings page. */
export function DesktopApp({ username }: { username: string }): JSX.Element {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [update, setUpdate] = useState({ busy: false, text: '', available: '' as string, confirm: false });
  const [message, setMessage] = useState('');
  const [password, setPassword] = useState('');
  const [logs, setLogs] = useState('');
  const [restartConfirm, setRestartConfirm] = useState(false);

  const loadStatus = () =>
    call<AppStatus>('worker_status')
      .then((value) => {
        setStatus(value);
        setSignedOut(false);
      })
      .catch((cause: Failure) => {
        if (cause?.code === 'unauthorized') setSignedOut(true);
        else setMessage(failureText(cause));
      });

  const checkUpdate = () => {
    setUpdate({ busy: true, text: '', available: '', confirm: false });
    call<{ current: string; available: string | null }>('check_update')
      .then((result) =>
        setUpdate({
          busy: false,
          available: result.available ?? '',
          confirm: false,
          text: result.available
            ? t('Доступна версия {0}', result.available)
            : t('Установлена последняя версия ({0})', result.current),
        }),
      )
      .catch((cause) =>
        setUpdate({
          busy: false,
          available: '',
          confirm: false,
          text: t('Не удалось проверить обновления: {0}', failureText(cause)),
        }),
      );
  };

  useEffect(() => {
    void call<AppSettings>('get_settings')
      .then(setSettings)
      .catch(() => undefined);
    void loadStatus();
    // The tray's «Check for updates» opens this page with ?check=1.
    if (new URLSearchParams(window.location.search).has('check')) checkUpdate();
  }, []);

  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await call('login', { url: window.location.origin, user: username, password });
      setPassword('');
      setMessage(t('Приложение вошло на хаб: вход продлевается сам, 30 дней с последнего использования.'));
      void loadStatus();
    } catch (cause) {
      setPassword('');
      setMessage(failureText(cause));
    }
  };

  const toggleAutostart = async (on: boolean) => {
    try {
      await call('set_autostart', { on });
      setSettings((current) => current && { ...current, autostart: on });
    } catch (cause) {
      setMessage(failureText(cause));
    }
  };

  const restart = async () => {
    setRestartConfirm(false);
    try {
      await call('restart_worker', { consent: true });
      setMessage(t('Воркер перезапущен.'));
      void loadStatus();
    } catch (cause) {
      setMessage(failureText(cause));
    }
  };

  return (
    <section className="panel desktop-app">
      <h2>{t('Приложение для Windows')}</h2>
      {message && <p role="status">{message}</p>}
      <dl>
        <dt>{t('Воркер')}</dt>
        <dd>
          {status
            ? `${settings?.workerId ?? ''} · ${status.workerState}${status.activeAgents ? ` · ${t('агентов: {0}', status.activeAgents)}` : ''}`
            : signedOut
              ? t('приложение не вошло на хаб')
              : t('проверка…')}
        </dd>
      </dl>
      {status?.warning && <p className="muted">{status.warning}</p>}
      {signedOut && (
        <form onSubmit={(event) => void signIn(event)}>
          <p className="muted">{t('Вход приложения истёк. Войдите ещё раз — дальше он будет продлеваться сам.')}</p>
          <label>
            {t('Пароль для {0}', username)}
            <input
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button className="ui-button ui-button-primary" type="submit" disabled={!password}>
            {t('Войти в приложении')}
          </button>
        </form>
      )}
      <div className="toolbar">
        <button className="ui-button" onClick={checkUpdate} disabled={update.busy}>
          {update.busy ? t('Проверяю…') : t('Проверить обновления')}
        </button>
        {update.text && <span role="status">{update.text}</span>}
        {update.available &&
          (update.confirm ? (
            <button
              className="ui-button ui-button-primary"
              onClick={() =>
                void call('update_app', { consent: true }).catch((cause) => setMessage(failureText(cause)))
              }
            >
              {t('Скачать, установить и перезапустить')}
            </button>
          ) : (
            <button className="ui-button" onClick={() => setUpdate({ ...update, confirm: true })}>
              {t('Обновить приложение')}
            </button>
          ))}
      </div>
      {settings && (
        <label className="check">
          <input
            type="checkbox"
            checked={settings.autostart}
            onChange={(event) => void toggleAutostart(event.target.checked)}
          />
          {t('Запускать при входе в Windows')}
        </label>
      )}
      <div className="toolbar">
        {restartConfirm ? (
          <button className="ui-button ui-button-danger" onClick={() => void restart()}>
            {status?.activeAgents ? t('Агенты работают — всё равно перезапустить') : t('Подтвердить перезапуск')}
          </button>
        ) : (
          <button className="ui-button" onClick={() => setRestartConfirm(true)}>
            {t('Перезапустить воркер')}
          </button>
        )}
        <button
          className="ui-button"
          onClick={() =>
            void call<string>('worker_logs', { lines: 200 })
              .then(setLogs)
              .catch((cause) => setMessage(failureText(cause)))
          }
        >
          {t('Журнал воркера')}
        </button>
        <button className="ui-button" onClick={() => void call('open_app_settings').catch(() => undefined)}>
          {t('Подключение машины…')}
        </button>
      </div>
      {logs && <pre className="desktop-logs">{logs}</pre>}
    </section>
  );
}
