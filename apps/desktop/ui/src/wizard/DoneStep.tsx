import { ipc } from '../ipc';
import { t } from '../i18n';
export function DoneStep() {
  return (
    <>
      <h1>{t('Готово')}</h1>
      <p>{t('Воркер подключён. Откройте панель и добавьте аккаунты.')}</p>
      <button onClick={() => ipc.openPanel('/settings/accounts')}>{t('Открыть панель → Settings → Accounts')}</button>
    </>
  );
}
