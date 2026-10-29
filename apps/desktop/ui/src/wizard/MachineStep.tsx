import { useState } from 'react';
import { ipc, type MachineReport } from '../ipc';
import { t } from '../i18n';
import { errorText } from '../App';
export function MachineStep({
  machine,
  onCheck,
  onError,
}: {
  machine: MachineReport | null;
  onCheck: () => void;
  onError: (error: unknown) => void;
}) {
  return (
    <>
      <h1>{t('Эта машина')}</h1>
      {!machine ? (
        <p>{t('Проверим WSL, systemd, Python, Git и доступные движки.')}</p>
      ) : (
        <>
          {machine.problems.length ? (
            <div className="problems">
              {machine.problems.map((problem) => (
                <div className="problem" key={problem.code}>
                  <strong>{errorText({ code: problem.code, message: problem.hint })}</strong>
                  <p>{problem.hint}</p>
                  {problem.code === 'wsl_missing' && <code>wsl --install</code>}
                </div>
              ))}
            </div>
          ) : (
            <p className="success">{t('Машина готова.')}</p>
          )}
          {(!machine.wslconfig.instanceIdleTimeoutOk || !machine.wslconfig.vmIdleTimeoutOk) && (
            <WslConfig onError={onError} />
          )}
          <button className="secondary" onClick={onCheck}>
            {t('Проверить снова')}
          </button>
        </>
      )}
    </>
  );
}
function WslConfig({ onError }: { onError: (error: unknown) => void }) {
  const [consent, setConsent] = useState(false);
  const [done, setDone] = useState(false);
  return (
    <div className="notice">
      <strong>.wslconfig</strong>
      <p>
        {t(
          'Эти параметры не дают WSL выключиться без открытого терминала. Можно добавить только отсутствующие строки; сначала создаётся резервная копия.',
        )}
      </p>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
        {t('Я согласен изменить .wslconfig')}
      </label>
      <button
        disabled={!consent}
        onClick={() =>
          ipc
            .fixWslconfig()
            .then(() => setDone(true))
            .catch(onError)
        }
      >
        {done ? t('Готово') : t('Исправить .wslconfig')}
      </button>
    </div>
  );
}
