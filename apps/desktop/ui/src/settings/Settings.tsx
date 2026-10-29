import { useEffect, useState } from 'react';
import { ipc, type AppError, type Settings as SettingsData } from '../ipc';
import { t } from '../i18n';
import { errorText } from '../App';
import { Frame, ErrorBox } from '../wizard/Frame';
import { LogsView } from './LogsView';

export function SettingsView({
  settings,
  onChange,
  showLogs,
  onLogsShown,
  updateVersion,
  checkRequest = 0,
}: {
  settings: SettingsData;
  onChange: (settings: SettingsData) => void;
  showLogs: boolean;
  onLogsShown: () => void;
  updateVersion: string | null;
  /** Bumped by the tray's «Check for updates»: run the check here, where its answer is visible. */
  checkRequest?: number;
}) {
  const [local, setLocal] = useState(settings);
  const [error, setError] = useState<AppError | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [status, setStatus] = useState<Awaited<ReturnType<typeof ipc.workerStatus>> | null>(null);
  const [restartConfirm, setRestartConfirm] = useState(false);
  const [updateConfirm, setUpdateConfirm] = useState(false);
  const [updateCheck, setUpdateCheck] = useState<{ busy: boolean; text: string; found: string | null }>({ busy: false, text: '', found: null });
  const checkUpdate = () => {
    setUpdateCheck({ busy: true, text: '', found: null });
    ipc
      .checkUpdate()
      .then((result) =>
        setUpdateCheck({
          busy: false,
          text: result.available ? `${t('Доступна версия')} ${result.available}` : `${t('Установлена последняя версия')} (${result.current})`,
          found: result.available,
        }),
      )
      .catch((cause: { message?: string }) => setUpdateCheck({ busy: false, text: `${t('Не удалось проверить обновления')}: ${cause?.message ?? cause}`, found: null }));
  };
  const shownVersion = updateVersion ?? updateCheck.found;
  useEffect(() => {
    if (checkRequest > 0) checkUpdate();
  }, [checkRequest]);
  useEffect(() => { void ipc.workerStatus().then(setStatus).catch(() => undefined); }, []);
  const save = async () => {
    try {
      onChange(await ipc.saveSettings(local));
    } catch (caught) {
      setError(caught as AppError);
    }
  };
  const disconnect = async (deleteFromHub: boolean) => {
    try {
      await ipc.disconnectMachine(deleteFromHub);
      onChange({ ...local, setupComplete: false });
    } catch (caught) {
      setError(caught as AppError);
    }
  };
  const setFailure = (caught: unknown) => setError(caught as AppError);
  const [signIn, setSignIn] = useState({ user: '', password: '', busy: false, done: false });
  // Sign in again from here: the app's hub session can expire (e.g. made before the 30-day sign-in existed).
  const submitSignIn = async (event: React.FormEvent) => {
    event.preventDefault();
    setSignIn({ ...signIn, busy: true, done: false });
    try {
      await ipc.login(local.hubUrl ?? '', signIn.user, signIn.password);
      setSignIn({ user: signIn.user, password: '', busy: false, done: true });
      setError(null);
      void ipc.workerStatus().then(setStatus).catch(() => undefined);
    } catch (caught) {
      setSignIn({ ...signIn, password: '', busy: false });
      setError(caught as AppError);
    }
  };
  return (
    <Frame>
      <ErrorBox error={error} errorText={errorText} />
      <h1>{t('Настройки')}</h1>
      <label>
        {t('Адрес хаба')}
        <input value={local.hubUrl ?? ''} onChange={(event) => setLocal({ ...local, hubUrl: event.target.value })} />
      </label>
      <label>
        Worker ID
        <input
          value={local.workerId ?? ''}
          readOnly={local.existingWorker}
          onChange={(event) => setLocal({ ...local, workerId: event.target.value })}
        />
      </label>
      <p>
        {t('Движки')}: {local.engines.join(', ') || '—'}
      </p>
      <p>
        <button className="secondary" onClick={checkUpdate} disabled={updateCheck.busy}>
          {updateCheck.busy ? t('Проверяю…') : t('Проверить обновления')}
        </button>{' '}
        {updateCheck.text && !shownVersion && <span role="status">{updateCheck.text}</span>}
      </p>
      {shownVersion && (
        <div className="notice" role="status">
          <strong>{t('Доступна версия')} {shownVersion}</strong>
          {!updateConfirm ? (
            <button className="secondary" onClick={() => setUpdateConfirm(true)}>{t('Обновить')}</button>
          ) : (
            <>
              <p>{status?.activeAgents ? t('Агенты работают. Обновление перезапустит приложение — подтвердите действие.') : t('Скачать и установить обновление?')}</p>
              <button className="danger" onClick={() => ipc.updateApp(Boolean(status?.activeAgents)).then(() => setUpdateConfirm(false)).catch(setFailure)}>{t('Подтвердить обновление')}</button>
              <button className="secondary" onClick={() => setUpdateConfirm(false)}>{t('Отмена')}</button>
            </>
          )}
        </div>
      )}
      {status?.warning && <div className="notice" role="status"><strong>{t('Предупреждение воркера')}</strong><p>{status.warning}</p></div>}
      <form className="sign-in" onSubmit={(event) => void submitSignIn(event)}>
        <h2>{t('Вход на хаб')}</h2>
        {signIn.done && <p role="status">{t('Вход выполнен: приложение будет продлевать его само (30 дней с последнего использования).')}</p>}
        <label>
          {t('Пользователь')}
          <input value={signIn.user} autoComplete="username" onChange={(event) => setSignIn({ ...signIn, user: event.target.value })} />
        </label>
        <label>
          {t('Пароль')}
          <input type="password" value={signIn.password} autoComplete="current-password" onChange={(event) => setSignIn({ ...signIn, password: event.target.value })} />
        </label>
        <button className="secondary" type="submit" disabled={signIn.busy || !signIn.user || !signIn.password}>
          {signIn.busy ? t('Вхожу…') : t('Войти')}
        </button>
      </form>
      <label className="check">
        <input
          type="checkbox"
          checked={local.autostart}
          onChange={async (event) => {
            const autostart = event.target.checked;
            setLocal({ ...local, autostart });
            try {
              await ipc.setAutostart(autostart);
            } catch (caught) {
              setFailure(caught);
            }
          }}
        />
        {t('Запускать при входе в Windows')}
      </label>
      <div className="actions">
        <button onClick={save}>{t('Сохранить')}</button>
        {!local.existingWorker && (
          <button className="secondary" onClick={() => ipc.reinstallWorker().catch(setFailure)}>
            {t('Переустановить воркер')}
          </button>
        )}
        {!restartConfirm ? (
          <button className="secondary" onClick={() => setRestartConfirm(true)}>{t('Перезапустить воркер')}</button>
        ) : (
          <div className="notice">
            <p>{status?.activeAgents ? t('Агенты работают. Перезапуск прервёт их — подтвердите действие.') : t('Перезапустить воркер?')}</p>
            <button className="danger" onClick={() => ipc.restartWorker(true).then(() => setRestartConfirm(false)).catch(setFailure)}>{t('Подтвердить перезапуск')}</button>
            <button className="secondary" onClick={() => setRestartConfirm(false)}>{t('Отмена')}</button>
          </div>
        )}
      </div>
      <LogsView open={showLogs} onShown={onLogsShown} onError={setFailure} />
      <h2>{t('Отключить машину')}</h2>
      {local.existingWorker ? (
        <>
          <p className="muted">
            {t(
              'Воркер установлен вручную (служба aihub-worker): приложение только следит за ним. Отключение лишь забудет его в приложении — служба и запись в хабе останутся.',
            )}
          </p>
          <button className="secondary" onClick={() => disconnect(false)}>
            {t('Забыть воркер в приложении')}
          </button>
        </>
      ) : (
        <>
          <p className="muted">{t('Остановит воркер на этой машине.')}</p>
          {!confirm ? (
            <button className="danger" onClick={() => setConfirm(true)}>
              {t('Отключить')}
            </button>
          ) : (
            <div className="notice">
              <p>{t('Удалить эту машину из хаба? Это отдельное действие и требует явного подтверждения.')}</p>
              <button className="danger" onClick={() => disconnect(true)}>
                {t('Удалить воркер в хабе')}
              </button>
              <button className="secondary" onClick={() => disconnect(false)}>
                {t('Отключить только локально')}
              </button>
            </div>
          )}
        </>
      )}
    </Frame>
  );
}
