import { useState } from 'react';
import { ipc, type AppError, type ExistingWorker, type MachineReport, type Settings } from '../ipc';
import { t } from '../i18n';
import { errorText } from '../App';
import { Frame, ErrorBox } from './Frame';
import { HubStep } from './HubStep';
import { LoginStep } from './LoginStep';
import { MachineStep } from './MachineStep';
import { EnginesStep } from './EnginesStep';
import { RegisterStep, workerIdPattern } from './RegisterStep';
import { InstallStep } from './InstallStep';
import { DoneStep } from './DoneStep';
import { SubscriptionsStep } from './SubscriptionsStep';

export function Wizard({
  settings,
  onComplete,
  machine,
  onMachine,
}: {
  settings: Settings;
  onComplete: (settings: Settings) => void;
  machine: MachineReport | null;
  onMachine: (machine: MachineReport) => void;
}) {
  const [step, setStep] = useState(0);
  const [error, setError] = useState<AppError | null>(null);
  const [hub, setHub] = useState(settings.hubUrl ?? '');
  const [user, setUser] = useState('admin');
  const [password, setPassword] = useState('');
  const [engines, setEngines] = useState(settings.engines);
  const [workerId, setWorkerId] = useState(settings.workerId ?? '');
  const [busy, setBusy] = useState(false);
  // A worker installed on this machine by hand for the same hub: offered instead of registering a second one.
  const [existing, setExisting] = useState<ExistingWorker | null>(null);
  const [useExisting, setUseExisting] = useState(false);

  const action = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await operation();
    } catch (caught) {
      setError(caught as AppError);
    } finally {
      setBusy(false);
    }
  };
  const next = () =>
    action(async () => {
      if (step === 0) setHub((await ipc.checkHub(hub)).url);
      if (step === 1) {
        await ipc.login(hub, user, password);
        setPassword('');
      }
      if (step === 2 && !machine) {
        // First show what the check found (problems, .wslconfig); the next click goes on.
        const report = await ipc.checkMachine();
        onMachine(report);
        if (!workerId) setWorkerId(report.defaultWorkerId);
        return;
      }
      if (step === 3 && engines.length === 0)
        throw { code: 'invalid_engine', message: 'Choose an engine' } satisfies AppError;
      if (step === 3) {
        const found = await ipc.detectExistingWorker(machine?.distro ?? settings.distro ?? '');
        const same = found && sameHub(found.hubUrl, hub) ? found : null;
        setExisting(same);
        setUseExisting(Boolean(same));
      }
      if (step === 4 && existing && useExisting) {
        await ipc.saveSettings({
          ...settings,
          hubUrl: hub,
          workerId: existing.workerId,
          distro: machine?.distro ?? settings.distro,
          engines,
          existingWorker: true,
          setupComplete: false,
        });
        setWorkerId(existing.workerId);
        await waitForOnline();
        setStep(6);
        return;
      }
      if (step === 4) {
        if (!workerIdPattern.test(workerId))
          throw { code: 'invalid_worker_id', message: 'Invalid worker id' } satisfies AppError;
        // Registration and installation read the hub, distro and engines from the saved settings.
        await ipc.saveSettings({
          ...settings,
          hubUrl: hub,
          workerId,
          distro: machine?.distro ?? settings.distro,
          engines,
          existingWorker: false,
          setupComplete: false,
        });
        await ipc.registerWorker(workerId, engines);
      }
      if (step === 5) {
        await ipc.installWorker();
        await waitForOnline();
        setStep(6);
        return;
      }
      setStep(step + 1);
    });
  const waitForOnline = async () => {
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      if ((await ipc.workerStatus()).workerState === 'online') return;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw { code: 'timeout', message: 'Worker did not become online' } satisfies AppError;
  };
  const complete = () =>
    action(async () => {
      const saved = await ipc.saveSettings({
        ...settings,
        hubUrl: hub,
        workerId,
        distro: machine?.distro ?? settings.distro,
        engines,
        existingWorker: Boolean(existing && useExisting),
        setupComplete: true,
      });
      await ipc.setAutostart(true);
      onComplete(saved);
    });
  const content = [
    <HubStep key="hub" value={hub} onChange={setHub} />,
    <LoginStep key="login" user={user} password={password} onUser={setUser} onPassword={setPassword} />,
    <MachineStep
      key="machine"
      machine={machine}
      onCheck={() => action(async () => onMachine(await ipc.checkMachine()))}
      onError={(caught) => setError(caught as AppError)}
    />,
    <EnginesStep key="engines" machine={machine} engines={engines} onChange={setEngines} />,
    <RegisterStep
      key="register"
      value={workerId}
      onChange={setWorkerId}
      existing={existing}
      useExisting={useExisting}
      onUseExisting={setUseExisting}
    />,
    <InstallStep key="install" />,
    <SubscriptionsStep key="subscriptions" onError={(caught) => setError(caught as AppError)} />,
    <DoneStep key="done" />,
  ];
  return (
    <Frame step={step}>
      <ErrorBox error={error} errorText={errorText} />
      {content[step]}
      <div className="actions">
        {step > 0 && step < 7 && (
          <button
            className="secondary"
            onClick={() => {
              setError(null);
              setStep(step - 1);
            }}
          >
            {t('Назад')}
          </button>
        )}
        {step < 5 && (
          <button onClick={next} disabled={busy}>
            {busy ? t('Проверка…') : step === 0 ? t('Проверить') : t('Далее')}
          </button>
        )}
        {step === 5 && (
          <button onClick={next} disabled={busy}>
            {busy ? t('Установка…') : t('Установить')}
          </button>
        )}
        {step === 6 && (
          <button onClick={() => setStep(7)} disabled={busy}>{t('Далее')}</button>
        )}
        {step === 7 && (
          <button onClick={complete} disabled={busy}>
            {t('Завершить')}
          </button>
        )}
      </div>
    </Frame>
  );
}

/** The same hub whatever the trailing slash or letter case of its address. */
function sameHub(left: string, right: string): boolean {
  const norm = (url: string) => url.trim().replace(/\/+$/, '').toLowerCase();
  return norm(left) === norm(right);
}
