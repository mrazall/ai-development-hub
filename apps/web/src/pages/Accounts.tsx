import { FormEvent, useState } from 'react';
import { api } from '../api/client';
import { ago, errorText, useApi } from '../api/useApi';
import type { AccountProfile, Worker } from '../api/types';
import { Dialog, EmptyState, ErrorBanner, Loading, StatusBadge } from '../components/ui';
import { t } from '../i18n';

const kinds = [
  ['claude_code_subscription', t('Claude Code — подписка')],
  ['codex_subscription', t('Codex — подписка')],
  ['anthropic_api', 'Anthropic API'],
  ['openai_api', 'OpenAI API'],
  ['gemini_api', 'Gemini'],
  ['openrouter', 'OpenRouter'],
  ['ollama', 'Ollama'],
  ['openai_compatible', 'OpenAI-compatible'],
] as const;
const subscriptionKinds = new Set(['claude_code_subscription', 'codex_subscription']);
const secretKinds = new Set(['anthropic_api', 'openai_api', 'gemini_api', 'openrouter']);

export function Accounts(): JSX.Element {
  const accounts = useApi<AccountProfile[]>('/accounts');
  const workers = useApi<Worker[]>('/workers');
  const missing = accounts.error.includes('(404)');
  const [showWizard, setShowWizard] = useState(false);
  const [selected, setSelected] = useState<AccountProfile | null>(null);
  const reload = () => accounts.reload();

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('НАСТРОЙКИ')}</p>
          <h1>{t('Аккаунты и модели')}</h1>
          <p className="muted">
            {t('Две независимые подписки Claude Code — два профиля; у каждого свой каталог настроек.')}
          </p>
        </div>
        <button onClick={() => setShowWizard(true)}>{t('Добавить аккаунт')}</button>
      </div>
      {missing ? (
        <div className="notice">
          <strong>{t('Бэкенд аккаунтов ещё не подключён')}</strong>
          <span>{t('API `/accounts` пока не зарегистрирован. Фейковые данные не показываются.')}</span>
        </div>
      ) : accounts.error ? (
        <ErrorBanner message={accounts.error} />
      ) : null}
      {!missing && !accounts.data ? <Loading /> : null}
      {!missing && accounts.data?.length === 0 ? <EmptyState>{t('Аккаунтов пока нет.')}</EmptyState> : null}
      {!missing && workers.data?.length === 0 && (
        <div className="notice" role="status">
          <strong>{t('Сначала зарегистрируйте worker')}</strong>
          <span>{t('Новый профиль нельзя подключить без безопасного места выполнения.')}</span>
        </div>
      )}
      <div className="account-grid">
        {accounts.data?.map((account) => (
          <AccountCard key={account.id} account={account} onChange={reload} onSelect={setSelected} />
        ))}
      </div>
      {showWizard && (
        <AccountWizard
          workers={workers.data ?? []}
          onClose={() => setShowWizard(false)}
          onCreated={() => {
            setShowWizard(false);
            reload();
          }}
        />
      )}
      {selected && (
        <AccountActions
          account={selected}
          workers={workers.data ?? []}
          onClose={() => setSelected(null)}
          onChange={() => {
            setSelected(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function AccountCard({
  account,
  onChange,
  onSelect,
}: {
  account: AccountProfile;
  onChange: () => void;
  onSelect: (account: AccountProfile) => void;
}): JSX.Element {
  const check = async () => {
    await api(`/accounts/${account.id}/check`, { method: 'POST' });
    onChange();
    for (let delay = 5000; delay <= 70000; delay += 5000) window.setTimeout(onChange, delay);
  };
  return (
    <article className="panel account-card">
      <div className="card-top">
        <div>
          <h2>{account.name}</h2>
          <p className="muted">{labelForKind(account.kind)}</p>
        </div>
        <StatusBadge value={account.status} />
      </div>
      <dl>
        <dt>Worker</dt>
        <dd>{account.worker_id}</dd>
        <dt>{t('Модель')}</dt>
        <dd>{account.default_model ?? t('не выбрана')}</dd>
        {account.secret_fingerprint && (
          <>
            <dt>{t('Отпечаток ключа')}</dt>
            <dd>
              <code>{account.secret_fingerprint}</code>
            </dd>
          </>
        )}
        {account.status_detail && (
          <>
            <dt>{t('Детали')}</dt>
            <dd>{account.status_detail}</dd>
          </>
        )}
        <dt>{t('Проверка')}</dt>
        <dd>{ago(account.checked_at)}</dd>
      </dl>
      <div className="card-actions">
        <button onClick={check}>{t('Проверить')}</button>
        <button className="button-secondary" onClick={() => onSelect(account)}>
          {t('Действия')}
        </button>
      </div>
    </article>
  );
}

function AccountWizard({
  workers,
  onClose,
  onCreated,
}: {
  workers: Worker[];
  onClose: () => void;
  onCreated: () => void;
}): JSX.Element {
  const [step, setStep] = useState(1);
  const [kind, setKind] = useState<string>(kinds[0][0]);
  const [form, setForm] = useState({ id: '', name: '', worker_id: workers[0]?.id ?? '', base_url: '', model: '' });
  const [error, setError] = useState('');
  const [created, setCreated] = useState<AccountProfile | null>(null);
  const [loginSteps, setLoginSteps] = useState<LoginStep[]>([]);
  const [secret, setSecret] = useState('');
  const [idEdited, setIdEdited] = useState(false);
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const updateName = (name: string) => {
    setForm((current) => ({ ...current, name, ...(idEdited ? {} : { id: profileIdFromName(name) }) }));
  };
  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await api<AccountProfile>('/accounts', {
        method: 'POST',
        body: JSON.stringify({
          id: form.id,
          name: form.name,
          kind,
          worker_id: form.worker_id,
          base_url: form.base_url || undefined,
        }),
      });
      setCreated(result);
      setStep(3);
    } catch (cause) {
      setError(errorText(cause, t('Не удалось создать аккаунт')));
    }
  };
  const sendSecret = async () => {
    try {
      await api(`/accounts/${created?.id}/secret`, { method: 'POST', body: JSON.stringify({ secret }) });
      setSecret('');
      setError(t('Ключ сохранён. Он больше не будет показан.'));
    } catch (cause) {
      setError(errorText(cause, t('Не удалось сохранить ключ')));
    }
  };
  const instructionsFor = async () => {
    try {
      const result = await api<{ steps: LoginStep[] }>(`/accounts/${created?.id}/login-instructions`, {
        method: 'POST',
      });
      setLoginSteps(result.steps);
    } catch (cause) {
      setError(errorText(cause, t('Не удалось получить инструкцию входа')));
    }
  };
  const check = async () => {
    try {
      await api(`/accounts/${created?.id}/check`, { method: 'POST' });
      onCreated();
    } catch (cause) {
      setError(errorText(cause, t('Проверка соединения не удалась')));
    }
  };
  return (
    <Dialog open title={t('Добавить аккаунт')} onClose={onClose}>
      <form
        className="panel modal-body create-form"
        onSubmit={
          step === 1
            ? (event) => {
                event.preventDefault();
                setStep(2);
              }
            : create
        }
      >
        <div className="panel-heading">
          <div>
            <p className="eyebrow">
              {t('ШАГ')} {step} {t('ИЗ 3')}
            </p>
            <h2>{t('Добавить аккаунт')}</h2>
          </div>
        </div>
        {error && <ErrorBanner message={error} />}
        {step === 1 && (
          <label>
            {t('Провайдер')}
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              {kinds.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>
          </label>
        )}
        {step === 2 && (
          <>
            <label>
              {t('ID профиля')}
              <input
                value={form.id}
                onChange={(event) => {
                  setIdEdited(true);
                  update('id', event.target.value);
                }}
                pattern="[a-z0-9][a-z0-9-]{1,62}"
                required
              />
              <small>{t('Короткое имя профиля внутри хаба, например codex-main. Не логин и не ID у провайдера')}</small>
            </label>
            <label>
              {t('Имя')}
              <input value={form.name} onChange={(event) => updateName(event.target.value)} required />
            </label>
            <label>
              Worker
              <select value={form.worker_id} onChange={(event) => update('worker_id', event.target.value)} required>
                {workers.map((worker) => (
                  <option key={worker.id} value={worker.id}>
                    {worker.id} · {worker.status}
                  </option>
                ))}
              </select>
            </label>
            {(kind === 'ollama' || kind === 'openai_compatible') && (
              <label>
                Base URL
                <input
                  type="url"
                  value={form.base_url}
                  onChange={(event) => update('base_url', event.target.value)}
                  placeholder="http://127.0.0.1:11434"
                  required
                />
              </label>
            )}
            <p className="muted">
              {t('Способ входа:')}{' '}
              {subscriptionKinds.has(kind)
                ? t('официальный CLI-вход на worker')
                : secretKinds.has(kind)
                  ? t('API-ключ')
                  : t('локальный endpoint')}
              .
            </p>
          </>
        )}
        {step === 3 && created && (
          <>
            <p>
              {t('Профиль')} <strong>{created.name}</strong> {t('создан.')}
            </p>
            {subscriptionKinds.has(kind) && (
              <div className="notice">
                <strong>{t('Войдите в аккаунт на компьютере с worker-ом')}</strong>
                {loginSteps.length > 0 ? (
                  <LoginSteps steps={loginSteps} />
                ) : (
                  <button type="button" onClick={instructionsFor}>
                    {t('Показать инструкцию входа')}
                  </button>
                )}
              </div>
            )}
            {secretKinds.has(kind) && (
              <>
                <label>
                  {t('API-ключ (передаётся один раз)')}
                  <input
                    type="password"
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                    autoComplete="off"
                  />
                </label>
                <button type="button" onClick={sendSecret} disabled={!secret}>
                  {t('Сохранить ключ')}
                </button>
              </>
            )}
            {!subscriptionKinds.has(kind) && (
              <label>
                {t('Модель по умолчанию')}
                <input
                  value={form.model}
                  onChange={(event) => update('model', event.target.value)}
                  placeholder={t('будет получена при проверке')}
                />
              </label>
            )}
            <button type="button" onClick={check}>
              {t('Проверить соединение')}
            </button>
          </>
        )}
        {step < 3 && <button type="submit">{t('Продолжить')}</button>}
      </form>
    </Dialog>
  );
}

function AccountActions({
  account,
  workers,
  onClose,
  onChange,
}: {
  account: AccountProfile;
  workers: Worker[];
  onClose: () => void;
  onChange: () => void;
}): JSX.Element {
  const [steps, setSteps] = useState<LoginStep[]>([]);
  const [error, setError] = useState('');
  const run = async (path: string, init?: RequestInit) => {
    try {
      await api(path, init);
      onChange();
    } catch (cause) {
      setError(errorText(cause, t('Операция не удалась')));
    }
  };
  const assign = async (worker_id: string) =>
    run(`/accounts/${account.id}`, { method: 'PATCH', body: JSON.stringify({ worker_id }) });
  const login = async () => {
    try {
      const result = await api<{ steps: LoginStep[] }>(`/accounts/${account.id}/login-instructions`, {
        method: 'POST',
      });
      setSteps(result.steps);
    } catch (cause) {
      setError(errorText(cause, t('Не удалось получить инструкцию')));
    }
  };
  return (
    <Dialog open title={t('Действия: {0}', account.name)} onClose={onClose}>
      <section className="panel modal-body create-form">
        <div className="panel-heading">
          <span className="muted">{t('Управление подключением и worker-профилем')}</span>
        </div>
        {error && <ErrorBanner message={error} />}
        <label>
          {t('Назначить worker')}
          <select value={account.worker_id} onChange={(event) => assign(event.target.value)}>
            {workers.map((worker) => (
              <option key={worker.id}>{worker.id}</option>
            ))}
          </select>
        </label>
        {account.status === 'disabled' ? (
          <div className="notice">
            {t('Профиль отключён: сессии и чаты его не используют.')}{' '}
            <button onClick={() => run(`/accounts/${account.id}/enable`, { method: 'POST' })}>{t('Включить')}</button>
          </div>
        ) : (
          <>
            {subscriptionKinds.has(account.kind) && steps.length === 0 && (
              <button onClick={login}>{t('Как войти в аккаунт — пошагово')}</button>
            )}
            {steps.length > 0 && <LoginSteps steps={steps} />}
            <button
              onClick={() => {
                void run(`/accounts/${account.id}/check`, { method: 'POST' });
                // The worker confirms within a minute; refresh the list until then.
                for (let delay = 5000; delay <= 70000; delay += 5000) window.setTimeout(onChange, delay);
              }}
            >
              {t('Проверить соединение')}
            </button>
          </>
        )}
        {account.status !== 'disabled' && (
          <button
            className="button-secondary"
            onClick={() => run(`/accounts/${account.id}/disable`, { method: 'POST' })}
          >
            {t('Отключить')}
          </button>
        )}
        {account.status === 'disabled' && (
          <button
            className="button-secondary"
            onClick={() => {
              if (window.confirm(t('Удалить отключённый аккаунт?')))
                run(`/accounts/${account.id}`, { method: 'DELETE' });
            }}
          >
            {t('Удалить')}
          </button>
        )}
      </section>
    </Dialog>
  );
}

type LoginStep = { text: string; command?: string };

function LoginSteps({ steps }: { steps: LoginStep[] }): JSX.Element {
  return (
    <ol className="login-steps">
      {steps.map((step, index) => (
        <li key={index}>
          <p>{step.text}</p>
          {step.command && (
            <div className="login-step-command">
              <code>{step.command}</code>
              <button
                type="button"
                className="button-secondary"
                onClick={() => void navigator.clipboard.writeText(step.command ?? '')}
              >
                {t('Скопировать')}
              </button>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

function labelForKind(kind: string): string {
  return kinds.find(([value]) => value === kind)?.[1] ?? kind;
}

function profileIdFromName(name: string): string {
  const transliteration: Record<string, string> = {
    а: 'a',
    б: 'b',
    в: 'v',
    г: 'g',
    д: 'd',
    е: 'e',
    ё: 'yo',
    ж: 'zh',
    з: 'z',
    и: 'i',
    й: 'y',
    к: 'k',
    л: 'l',
    м: 'm',
    н: 'n',
    о: 'o',
    п: 'p',
    р: 'r',
    с: 's',
    т: 't',
    у: 'u',
    ф: 'f',
    х: 'h',
    ц: 'ts',
    ч: 'ch',
    ш: 'sh',
    щ: 'sch',
    ъ: '',
    ы: 'y',
    ь: '',
    э: 'e',
    ю: 'yu',
    я: 'ya',
  };
  const normalized = name.toLowerCase().replace(/[а-яё]/g, (letter) => transliteration[letter] ?? letter);
  return (
    normalized
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 63) || 'profile'
  );
}
