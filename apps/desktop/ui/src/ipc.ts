import { invoke as tauriInvoke } from '@tauri-apps/api/core';

export type ErrorCode =
  | 'invalid_url'
  | 'insecure_url'
  | 'network'
  | 'tls'
  | 'not_a_hub'
  | 'http'
  | 'unauthorized'
  | 'forbidden'
  | 'not_logged_in'
  | 'wsl_missing'
  | 'distro_missing'
  | 'systemd_off'
  | 'python_old'
  | 'git_missing'
  | 'invalid_worker_id'
  | 'invalid_engine'
  | 'worker_exists'
  | 'install_failed'
  | 'timeout'
  | 'io'
  | 'internal';
export type AppError = { code: ErrorCode; message: string; detail?: string };
export type MachineReport = {
  wslInstalled: boolean;
  distros: { name: string; state: string; version: number; isDefault: boolean }[];
  distro: string | null;
  systemd: boolean;
  python: string | null;
  pythonOk: boolean;
  git: boolean;
  engines: { claude_code: boolean; codex: boolean };
  wslconfig: { instanceIdleTimeoutOk: boolean; vmIdleTimeoutOk: boolean };
  computerName: string;
  defaultWorkerId: string;
  problems: { code: ErrorCode; hint: string }[];
};
export type Settings = {
  hubUrl: string | null;
  workerId: string | null;
  distro: string | null;
  engines: string[];
  autostart: boolean;
  setupComplete: boolean;
  /** This machine's hand-installed worker (unit aihub-worker) is adopted: watched, never installed. */
  existingWorker: boolean;
  unitName: string;
};
export type ExistingWorker = { workerId: string; hubUrl: string; active: boolean };
export type FoundLogin = { workerId: string; engine: 'claude' | 'codex'; identity: string | null; kind: string };
export type AccountProfile = {
  id: string;
  name: string;
  kind: string;
  workerId: string;
  status: string;
  identity: string | null;
};
export type CliInstall = { engine: 'claude' | 'codex' | 'node'; command: string; installed: boolean };
export type HubInfo = { url: string; version: string; demo: boolean };
// As types.rs WorkerStatus serializes it: `hub` is the hub's address, the worker's state in the hub is
// `workerState` (the wizard waited for hub === 'online' and never got it).
export type Status = {
  unit: 'active' | 'inactive' | 'failed' | 'unknown';
  hub: string;
  hubReachable: boolean;
  workerId: string | null;
  workerState: 'online' | 'offline' | 'unknown' | string;
  pendingApprovals: number;
  activeAgents: number;
  workerVersion: string | null;
  workerOutdated: boolean;
  warning: string | null;
};
export type WorkerInstall = { version: string; path: string };
export type Ipc = {
  checkHub(url: string): Promise<HubInfo>;
  login(url: string, user: string, password: string): Promise<{ username: string; isAdmin: boolean }>;
  checkMachine(): Promise<MachineReport>;
  detectExistingWorker(distro: string): Promise<ExistingWorker | null>;
  registerWorker(id: string, engines: string[]): Promise<{ id: string }>;
  installWorker(): Promise<WorkerInstall>;
  workerStatus(): Promise<Status>;
  workerLogs(lines?: number): Promise<string>;
  restartWorker(consent?: boolean): Promise<null>;
  updateApp(consent?: boolean): Promise<null>;
  checkUpdate(): Promise<{ current: string; available: string | null }>;
  setAutostart(on: boolean): Promise<null>;
  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<Settings>;
  fixWslconfig(): Promise<{ backupPath: string; changed: boolean }>;
  disconnectMachine(deleteFromHub: boolean): Promise<null>;
  reinstallWorker(): Promise<WorkerInstall>;
  openPanel(path?: string): Promise<null>;
  foundLogins(): Promise<FoundLogin[]>;
  accounts(): Promise<AccountProfile[]>;
  createSubscription(engine: 'claude' | 'codex', adoptFoundLogin?: boolean): Promise<AccountProfile>;
  loginAccount(id: string): Promise<null>;
  cliInstallCommand(engine: 'claude' | 'codex' | 'node'): Promise<CliInstall>;
  installCli(engine: 'claude' | 'codex' | 'node'): Promise<CliInstall>;
};

const mockMachine: MachineReport = {
  wslInstalled: true,
  distros: [{ name: 'Ubuntu', state: 'Running', version: 2, isDefault: true }],
  distro: 'Ubuntu',
  systemd: true,
  python: '3.12.3',
  pythonOk: true,
  git: true,
  engines: { claude_code: true, codex: true },
  wslconfig: { instanceIdleTimeoutOk: true, vmIdleTimeoutOk: true },
  computerName: 'demo-pc',
  defaultWorkerId: 'demo-pc',
  problems: [],
};
let mockSettings: Settings = {
  hubUrl: null,
  workerId: null,
  distro: null,
  engines: [],
  autostart: true,
  setupComplete: false,
  existingWorker: false,
  unitName: '',
};
const mock: Ipc = {
  checkHub: async (url) => ({ url: url.replace(/\/$/, ''), version: 'dev', demo: true }),
  login: async () => ({ username: 'admin', isAdmin: true }),
  checkMachine: async () => mockMachine,
  detectExistingWorker: async () => null,
  registerWorker: async (id) => ({ id }),
  installWorker: async () => ({ version: 'dev', path: 'mock' }),
  workerStatus: async () => ({
    unit: 'active',
    hub: 'https://hub.test',
    hubReachable: true,
    workerId: 'demo-pc',
    workerState: 'online',
    pendingApprovals: 0,
    activeAgents: 0,
    workerVersion: null,
    workerOutdated: false,
    warning: null,
  }),
  workerLogs: async () => 'mock worker log',
  restartWorker: async () => null,
  updateApp: async () => null,
  checkUpdate: async () => ({ current: '0.0.0', available: null }),
  setAutostart: async (on) => {
    mockSettings = { ...mockSettings, autostart: on };
    return null;
  },
  getSettings: async () => mockSettings,
  saveSettings: async (s) => {
    mockSettings = s;
    return s;
  },
  fixWslconfig: async () => ({ backupPath: '', changed: true }),
  disconnectMachine: async () => null,
  reinstallWorker: async () => ({ version: 'dev', path: 'mock' }),
  openPanel: async () => null,
  foundLogins: async () => [],
  accounts: async () => [],
  createSubscription: async (engine) => ({ id: `${engine}-1`, name: `${engine} 1`, kind: `${engine}_subscription`, workerId: 'demo-pc', status: 'pending_login', identity: null }),
  loginAccount: async () => null,
  cliInstallCommand: async (engine) => ({ engine, command: `~/.local/share/aihub-worker/current/scripts/install-cli.sh ${engine} --dry-run`, installed: false }),
  installCli: async (engine) => ({ engine, command: `~/.local/share/aihub-worker/current/scripts/install-cli.sh ${engine}`, installed: true }),
};
const useMock =
  import.meta.env.VITE_USE_MOCK === 'true' ||
  typeof window === 'undefined' ||
  !(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
function call<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  return tauriInvoke<T>(name, args).catch((error) => {
    throw normalizeError(error);
  });
}
function normalizeError(error: unknown): AppError {
  if (error && typeof error === 'object' && 'code' in error && 'message' in error) return error as AppError;
  return { code: 'internal', message: String(error) };
}
export const ipc: Ipc = useMock
  ? mock
  : {
      checkHub: (url) => call('check_hub', { url }),
      login: (url, user, password) => call('login', { url, user, password }),
      checkMachine: () => call('check_machine'),
      detectExistingWorker: (distro) => call('detect_existing_worker', { distro }),
      registerWorker: (id, engines) => call('register_worker', { id, engines }),
      installWorker: () => call('install_worker'),
      workerStatus: () => call('worker_status'),
      workerLogs: (lines) => call('worker_logs', { lines }),
      restartWorker: (consent = false) => call('restart_worker', { consent }),
      updateApp: (consent = false) => call('update_app', { consent }),
      checkUpdate: () => call('check_update'),
      setAutostart: (on) => call('set_autostart', { on }),
      getSettings: () => call('get_settings'),
      saveSettings: (settings) => call('save_settings', { settings }),
      fixWslconfig: () => call('fix_wslconfig'),
      disconnectMachine: (deleteFromHub) => call('disconnect_machine', { deleteFromHub }),
      reinstallWorker: () => call('reinstall_worker'),
      openPanel: (path) => call('open_panel', path === undefined ? {} : { path }),
      foundLogins: () => call('found_logins'),
      accounts: () => call('accounts'),
      createSubscription: (engine, adoptFoundLogin) => call('create_subscription', { engine, adoptFoundLogin }),
      loginAccount: (id) => call('login_account', { id }),
      cliInstallCommand: (engine) => call('cli_install_command', { engine }),
      installCli: (engine) => call('install_cli', { engine }),
    };
