import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ipc } from './ipc';
import { SubscriptionsStep } from './wizard/SubscriptionsStep';

const machine = {
  wslInstalled: true,
  distros: [],
  distro: 'Ubuntu',
  systemd: true,
  python: '3.12.3',
  pythonOk: true,
  git: true,
  engines: { claude_code: true, codex: false },
  wslconfig: { instanceIdleTimeoutOk: true, vmIdleTimeoutOk: true },
  computerName: 'pc',
  defaultWorkerId: 'pc',
  problems: [],
};
const settings = {
  hubUrl: null,
  workerId: null,
  distro: null,
  engines: [],
  autostart: true,
  setupComplete: false,
  existingWorker: false,
  unitName: '',
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(ipc, 'getSettings').mockResolvedValue({ ...settings });
  vi.spyOn(ipc, 'checkHub').mockResolvedValue({ url: 'https://hub.test', version: '1', demo: false });
  vi.spyOn(ipc, 'login').mockResolvedValue({ username: 'admin', isAdmin: true });
  vi.spyOn(ipc, 'checkMachine').mockResolvedValue(machine);
  vi.spyOn(ipc, 'detectExistingWorker').mockResolvedValue(null);
  vi.spyOn(ipc, 'registerWorker').mockResolvedValue({ id: 'pc' });
  vi.spyOn(ipc, 'installWorker').mockResolvedValue({ version: '1', path: 'x' });
  vi.spyOn(ipc, 'workerStatus').mockResolvedValue({
    unit: 'active',
    hub: 'https://hub.test',
    workerId: 'pc',
    workerState: 'online',
    hubReachable: true,
    pendingApprovals: 0,
    activeAgents: 0,
    workerVersion: null,
    workerOutdated: false,
    warning: null,
  });
  vi.spyOn(ipc, 'saveSettings').mockImplementation(async (value) => value);
  vi.spyOn(ipc, 'setAutostart').mockResolvedValue(null);
  vi.spyOn(ipc, 'foundLogins').mockResolvedValue([]);
  vi.spyOn(ipc, 'accounts').mockResolvedValue([]);
  vi.spyOn(ipc, 'createSubscription').mockResolvedValue({ id: 'claude-1', name: 'Claude 1', kind: 'claude_code_subscription', workerId: 'pc', status: 'pending_login', identity: null });
  vi.spyOn(ipc, 'loginAccount').mockResolvedValue(null);
  vi.spyOn(ipc, 'fixWslconfig').mockResolvedValue({ backupPath: 'backup', changed: true });
  vi.spyOn(ipc, 'disconnectMachine').mockResolvedValue(null);
  vi.spyOn(ipc, 'cliInstallCommand').mockImplementation(async (engine) => ({ engine, command: `${engine} --dry-run`, installed: false }));
  vi.spyOn(ipc, 'installCli').mockImplementation(async (engine) => ({ engine, command: engine, installed: true }));
});

async function hubToLogin() {
  render(<App />);
  await screen.findByRole('heading', { name: 'Хаб' });
  fireEvent.click(screen.getByRole('button', { name: 'Проверить' }));
  await screen.findByRole('heading', { name: 'Вход' });
}
async function toEngines() {
  await hubToLogin();
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
  await screen.findByRole('heading', { name: 'Эта машина' });
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
  // The first click shows what the check found; the second goes on.
  await screen.findByText('Машина готова.');
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
  await screen.findByRole('heading', { name: 'Движки' });
}

describe('desktop wizard', () => {
  it('renders the hub step', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Хаб' })).toBeInTheDocument();
  });
  it('checks the hub and advances to login', async () => {
    await hubToLogin();
    expect(ipc.checkHub).toHaveBeenCalledWith('');
  });
  it('renders a translated contract error', async () => {
    vi.mocked(ipc.checkHub).mockRejectedValue({ code: 'not_a_hub', message: 'raw' });
    render(<App />);
    await screen.findByRole('heading', { name: 'Хаб' });
    fireEvent.click(screen.getByRole('button', { name: 'Проверить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка: not_a_hub');
  });
  it('clears password after login', async () => {
    await hubToLogin();
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Эта машина' });
    expect(screen.queryByDisplayValue('secret')).not.toBeInTheDocument();
  });
  it('checks the machine before showing engines', async () => {
    await toEngines();
    expect(ipc.checkMachine).toHaveBeenCalledOnce();
    expect(screen.getByRole('checkbox', { name: /claude_code/ })).toBeEnabled();
  });
  it('shows only engines found on the machine', async () => {
    await toEngines();
    expect(screen.getByRole('checkbox', { name: /codex/ })).toBeDisabled();
  });
  it('requires an engine selection', async () => {
    await toEngines();
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка: invalid_engine');
  });
  it('validates worker IDs with the contract regex', async () => {
    await toEngines();
    fireEvent.click(screen.getByRole('checkbox', { name: /claude_code/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Регистрация' });
    fireEvent.change(screen.getByLabelText('Worker ID'), { target: { value: 'BAD ID' } });
    expect(screen.getByText('Ошибка: invalid_worker_id')).toBeInTheDocument();
  });
  it('registers with selected engines', async () => {
    await toEngines();
    fireEvent.click(screen.getByRole('checkbox', { name: /claude_code/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Регистрация' });
    fireEvent.change(screen.getByLabelText('Worker ID'), { target: { value: 'pc-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Установка' });
    expect(ipc.registerWorker).toHaveBeenCalledWith('pc-1', ['claude_code']);
  });
  it('waits for the worker to become online', async () => {
    await toEngines();
    fireEvent.click(screen.getByRole('checkbox', { name: /claude_code/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Регистрация' });
    fireEvent.change(screen.getByLabelText('Worker ID'), { target: { value: 'pc' } });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Установка' });
    fireEvent.click(screen.getByRole('button', { name: 'Установить' }));
    await screen.findByRole('heading', { name: 'Подписки' });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Готово' });
    expect(ipc.workerStatus).toHaveBeenCalled();
  });
  it('requires consent before changing wslconfig', async () => {
    const problemMachine = { ...machine, wslconfig: { instanceIdleTimeoutOk: false, vmIdleTimeoutOk: true } };
    vi.mocked(ipc.checkMachine).mockResolvedValue(problemMachine);
    await hubToLogin();
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Эта машина' });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText('Машина готова.'); // results (with the .wslconfig offer) stay on screen
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Движки' });
    expect(ipc.fixWslconfig).not.toHaveBeenCalled();
  });
  it('keeps hub deletion behind a separate confirmation', async () => {
    vi.mocked(ipc.getSettings).mockResolvedValue({
      ...settings,
      setupComplete: true,
      hubUrl: 'https://hub.test',
      workerId: 'pc',
    });
    render(<App />);
    await screen.findByRole('heading', { name: 'Настройки' });
    fireEvent.click(screen.getByRole('button', { name: 'Отключить' }));
    expect(await screen.findByText(/Удалить эту машину/)).toBeInTheDocument();
    expect(ipc.disconnectMachine).not.toHaveBeenCalled();
  });
  it('saves autostart changes and can disconnect locally', async () => {
    vi.mocked(ipc.getSettings).mockResolvedValue({ ...settings, setupComplete: true });
    render(<App />);
    await screen.findByRole('heading', { name: 'Настройки' });
    fireEvent.click(screen.getByRole('checkbox', { name: /Запускать/ }));
    expect(ipc.setAutostart).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getByRole('button', { name: 'Отключить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отключить только локально' }));
    await waitFor(() => expect(ipc.disconnectMachine).toHaveBeenCalledWith(false));
  });
});

describe('found in the live run', () => {
  it('offers found logins and opens the login command for an account', async () => {
    vi.mocked(ipc.foundLogins).mockResolvedValue([{ workerId: 'pc', engine: 'claude', identity: 'owner', kind: 'subscription' }]);
    vi.mocked(ipc.accounts).mockResolvedValue([{ id: 'claude-1', name: 'Claude', kind: 'claude_code_subscription', workerId: 'pc', status: 'pending_login', identity: null }]);
    render(<SubscriptionsStep onError={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Использовать найденный вход' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ Claude' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ Codex' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
    await waitFor(() => expect(ipc.loginAccount).toHaveBeenCalledWith('claude-1'));
  });

  it('can finish without logging in', async () => {
    await toEngines();
    fireEvent.click(screen.getByLabelText(/claude_code/));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Регистрация' });
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Установка' });
    fireEvent.click(screen.getByRole('button', { name: 'Установить' }));
    await screen.findByRole('heading', { name: 'Подписки' });
    expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled();
  });

  it('shows dry-run command before CLI install and asks consent before Node', async () => {
    const missingCodex = { ...machine, engines: { claude_code: true, codex: false } };
    vi.mocked(ipc.checkMachine).mockResolvedValue(missingCodex);
    vi.mocked(ipc.cliInstallCommand).mockResolvedValue({ engine: 'codex', command: 'codex --dry-run', installed: false });
    await toEngines();
    fireEvent.click(screen.getByRole('button', { name: /Показать команду установки/ }));
    await screen.findByText('codex --dry-run');
    expect(ipc.installCli).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Показать команду Node.js' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Показать команду Node.js' }));
    expect(ipc.cliInstallCommand).toHaveBeenCalledWith('node');
  });

  it('saves the hub before registering and prefills the worker id', async () => {
    await toEngines();
    fireEvent.click(screen.getByLabelText(/claude_code/));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Регистрация' });
    expect((screen.getByLabelText('Worker ID') as HTMLInputElement).value).toBe('pc');
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await waitFor(() => expect(ipc.registerWorker).toHaveBeenCalled());
    const saved = vi.mocked(ipc.saveSettings).mock.calls[0][0];
    expect(saved).toMatchObject({ hubUrl: 'https://hub.test', workerId: 'pc', distro: 'Ubuntu' });
    expect(vi.mocked(ipc.saveSettings).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(ipc.registerWorker).mock.invocationCallOrder[0],
    );
  });
});

describe('a worker already installed on this machine', () => {
  it('is adopted instead of registering a second one', async () => {
    // The owner's PC: aihub-worker (pc-wsl) runs for the same hub; a second worker would have no accounts.
    vi.mocked(ipc.detectExistingWorker).mockResolvedValue({
      workerId: 'pc-wsl',
      hubUrl: 'https://hub.test/',
      active: true,
    });
    await toEngines();
    fireEvent.click(screen.getByLabelText(/claude_code/));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText(/Использовать подключённый воркер/);
    expect(screen.queryByLabelText('Worker ID')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByRole('heading', { name: 'Подписки' });
    expect(ipc.registerWorker).not.toHaveBeenCalled();
    expect(ipc.installWorker).not.toHaveBeenCalled();
    expect(vi.mocked(ipc.saveSettings).mock.calls[0][0]).toMatchObject({ workerId: 'pc-wsl', existingWorker: true });
  });

  it('a new worker is still possible', async () => {
    vi.mocked(ipc.detectExistingWorker).mockResolvedValue({
      workerId: 'pc-wsl',
      hubUrl: 'https://hub.test',
      active: true,
    });
    await toEngines();
    fireEvent.click(screen.getByLabelText(/claude_code/));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    fireEvent.click(await screen.findByLabelText(/Новый воркер/));
    expect(screen.getByLabelText('Worker ID')).toBeInTheDocument();
  });

  it('is not offered for another hub', async () => {
    vi.mocked(ipc.detectExistingWorker).mockResolvedValue({
      workerId: 'pc-wsl',
      hubUrl: 'https://other.hub',
      active: true,
    });
    await toEngines();
    fireEvent.click(screen.getByLabelText(/claude_code/));
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByLabelText('Worker ID');
    expect(screen.queryByText(/Использовать подключённый воркер/)).toBeNull();
  });
});
