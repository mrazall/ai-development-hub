import { useEffect, useState } from 'react';
import { ipc } from '../ipc';
import { t } from '../i18n';
export function LogsView({
  open,
  onShown,
  onError,
}: {
  open: boolean;
  onShown: () => void;
  onError: (error: unknown) => void;
}) {
  const [logs, setLogs] = useState('');
  useEffect(() => {
    if (!open) return;
    ipc.workerLogs(200).then(setLogs).then(onShown).catch(onError);
  }, [open, onError, onShown]);
  return (
    <section>
      <h2>{t('Журнал воркера')}</h2>
      <button className="secondary" onClick={() => ipc.workerLogs(200).then(setLogs).catch(onError)}>
        {t('Показать журнал')}
      </button>
      {logs && <pre className="logs">{logs}</pre>}
    </section>
  );
}
