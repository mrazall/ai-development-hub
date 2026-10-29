import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { ipc, type AppError, type MachineReport, type Settings } from './ipc';
import { t } from './i18n';
import { Frame } from './wizard/Frame';
import { Wizard } from './wizard/Wizard';
import { SettingsView } from './settings/Settings';

const fallbackSettings: Settings = {
  hubUrl: null,
  workerId: null,
  distro: null,
  engines: [],
  autostart: true,
  setupComplete: false,
  existingWorker: false,
  unitName: '',
};

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [machine, setMachine] = useState<MachineReport | null>(null);
  const [logsRequested, setLogsRequested] = useState(false);
  const [updateVersion, setUpdateVersion] = useState<string | null>(null);
  const [checkRequest, setCheckRequest] = useState(0);

  useEffect(() => {
    ipc
      .getSettings()
      .then(setSettings)
      .catch(() => setSettings(fallbackSettings));
    if (!(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) return;
    let disposed = false;
    const unlisten = Promise.all([
      listen('navigate', () => {
        if (!disposed) setSettings((current) => current && { ...current, setupComplete: true });
      }),
      listen('show-logs', () => {
        if (!disposed) setLogsRequested(true);
      }),
      listen('worker-status', () => undefined),
      listen('check-updates', () => {
        if (!disposed) setCheckRequest((n) => n + 1);
      }),
      listen<string>('update-available', (event) => setUpdateVersion(event.payload)),
    ]);
    return () => {
      disposed = true;
      void unlisten.then((stop) => stop.forEach((unsubscribe) => unsubscribe()));
    };
  }, []);

  if (!settings)
    return (
      <Frame>
        <p>{t('Загрузка…')}</p>
      </Frame>
    );
  if (!settings.setupComplete)
    return <Wizard settings={settings} onComplete={setSettings} onMachine={setMachine} machine={machine} />;
  return (
    <SettingsView
      settings={settings}
      onChange={setSettings}
      showLogs={logsRequested}
      onLogsShown={() => setLogsRequested(false)}
      updateVersion={updateVersion}
      checkRequest={checkRequest}
    />
  );
}

export function errorText(error: { code: string; message: string }) {
  const translated = t(`desktop.err.${error.code}`);
  return translated === `desktop.err.${error.code}` ? error.message : translated;
}
