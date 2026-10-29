import type { ChangeEvent } from 'react';
import type { MachineReport } from '../ipc';
import { t } from '../i18n';
import { ipc } from '../ipc';
import { useState } from 'react';
export function EnginesStep({
  machine,
  engines,
  onChange,
}: {
  machine: MachineReport | null;
  engines: string[];
  onChange: (engines: string[]) => void;
}) {
  const [commands, setCommands] = useState<Record<string, string>>({});
  const [installing, setInstalling] = useState<string | null>(null);
  const [nodeConsent, setNodeConsent] = useState(false);
  const toggle = (engine: string) => (event: ChangeEvent<HTMLInputElement>) =>
    onChange(event.target.checked ? [...engines, engine] : engines.filter((item) => item !== engine));
  const showCommand = async (engine: 'claude' | 'codex' | 'node', key = engine) => {
    const result = await ipc.cliInstallCommand(engine);
    setCommands((old) => ({ ...old, [key]: result.command }));
  };
  return (
    <>
      <h1>{t('Движки')}</h1>
      <p>{t('Выберите найденные на этой машине движки.')}</p>
      {(['claude_code', 'codex'] as const).map((engine) => (
        <label className="check" key={engine}>
          <input
            type="checkbox"
            disabled={!machine?.engines[engine]}
            checked={engines.includes(engine)}
            onChange={toggle(engine)}
          />
          {engine}
          {!machine?.engines[engine] && <span className="muted"> ({t('не найден')})</span>}
          {!machine?.engines[engine] && <button type="button" className="secondary" onClick={() => showCommand(engine === 'claude_code' ? 'claude' : 'codex')}>
            {t('Показать команду установки')}
          </button>}
          {commands[engine] && <div className="notice"><code>{commands[engine]}</code>
            {engine === 'codex' && <>
              <p>{t('Codex требует Node.js; сначала проверьте команду Node.js и только потом запускайте установку.')}</p>
              {!commands.node && <button type="button" className="secondary" onClick={() => showCommand('node')}>
                {t('Показать команду Node.js')}
              </button>}
              {commands.node && (
                <>
                  <p><code>{commands.node}</code></p>
                  <div className="check">
                    <input type="checkbox" checked={nodeConsent} onChange={(event) => setNodeConsent(event.target.checked)} />
                    {t('Я понимаю, что Node.js будет установлен в WSL для работы Codex.')}
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    disabled={installing === 'node' || !nodeConsent}
                    onClick={async () => {
                      setInstalling('node');
                      try {
                        await ipc.installCli('node');
                      } finally {
                        setInstalling(null);
                      }
                    }}
                  >{t('Установить Node.js')}</button>
                </>
              )}
            </>}
            <button
              type="button"
              disabled={installing === engine}
              onClick={async () => {
                setInstalling(engine);
                try {
                  await ipc.installCli(engine === 'claude_code' ? 'claude' : 'codex');
                } finally {
                  setInstalling(null);
                }
              }}
            >{t('Запустить установку')}</button>
          </div>}
        </label>
      ))}
    </>
  );
}
