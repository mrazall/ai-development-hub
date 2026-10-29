import { useEffect, useState } from 'react';
import { ipc, type AccountProfile, type FoundLogin } from '../ipc';
import { t } from '../i18n';

export function SubscriptionsStep({ onError }: { onError: (error: unknown) => void }) {
  const [found, setFound] = useState<FoundLogin[]>([]);
  const [accounts, setAccounts] = useState<AccountProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const refresh = () => ipc.foundLogins().then(setFound).then(() => ipc.accounts()).then(setAccounts).catch(onError);
  useEffect(() => { void refresh(); }, []);
  const add = async (engine: 'claude' | 'codex', adopt = false) => {
    setBusy(true);
    try { await ipc.createSubscription(engine, adopt); await refresh(); } catch (error) { onError(error); } finally { setBusy(false); }
  };
  return <>
    <h1>{t('Подписки')}</h1>
    <p>{t('Вход не обязателен: аккаунты можно добавить позже в панели.')}</p>
    {found.map((login) => <div className="choice" key={`${login.workerId}-${login.engine}`}>
      <strong>{login.engine === 'claude' ? 'Claude Code' : 'Codex'}{login.identity ? ` — ${login.identity}` : ''}</strong>
      <p className="muted">{t('Найден вход на этой машине.')}</p>
      <button disabled={busy} onClick={() => add(login.engine, true)}>{t('Использовать найденный вход')}</button>
    </div>)}
    {accounts.map((account) => <div className="choice" key={account.id}>
      <strong>{account.name}</strong><span className="muted"> — {account.status}{account.identity ? ` — ${account.identity}` : ''}</span>
      {account.status !== 'connected' && <button className="secondary" disabled={busy} onClick={() => ipc.loginAccount(account.id).catch(onError)}>{t('Войти')}</button>}
    </div>)}
    <div className="actions">
      <button className="secondary" disabled={busy} onClick={() => add('claude')}>+ Claude</button>
      <button className="secondary" disabled={busy} onClick={() => add('codex')}>+ Codex</button>
    </div>
    <button className="secondary" disabled={busy} onClick={refresh}>{t('Обновить')}</button>
  </>;
}
