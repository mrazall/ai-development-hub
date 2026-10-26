import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { accountCapturedAt, accountStale } from '../api/types-limits';
import type { AccountLimitWindow, AccountLimits, LimitsResponse } from '../api/types-limits';
import { useApi } from '../api/useApi';
import { ErrorBanner, Loading } from '../components/ui';
import { t } from '../i18n';

function accountsFrom(data: LimitsResponse | null): AccountLimits[] {
  if (Array.isArray(data)) return data;
  return data?.accounts ?? data?.limits ?? [];
}

function windowLabel(kind: string): string {
  return kind === 'seven_day' ? t('Неделя') : t('5 часов');
}

function resetDate(value: number | string): Date {
  const numeric = typeof value === 'number' ? value : Number(value);
  return new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric);
}

function resetIn(value: number | string): string {
  const minutes = Math.max(0, Math.round((resetDate(value).getTime() - Date.now()) / 60000));
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return hours ? t('сброс через {0} ч {1} мин', hours, remainder) : t('сброс через {0} мин', remainder);
}

function percent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function tone(value: number): string {
  return value > 90 ? 'danger' : value >= 75 ? 'warning' : 'neutral';
}

function LimitBar({ item }: { item: AccountLimitWindow }): JSX.Element {
  const value = percent(item.used_percent);
  const exact = resetDate(item.resets_at);
  return (
    <div className="limit-window">
      <div className="limit-window-heading">
        <span>{windowLabel(item.kind)}</span>
        <strong>{Math.round(value)}%</strong>
      </div>
      <div
        className={`limit-bar ${tone(value)}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <span style={{ width: `${value}%` }} />
      </div>
      <div className="limit-window-meta">
        <span>{resetIn(item.resets_at)}</span>
        <time dateTime={exact.toISOString()} title={exact.toLocaleString()}>
          {exact.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </time>
      </div>
    </div>
  );
}

export function Limits(): JSX.Element {
  const result = useApi<LimitsResponse>('/limits');
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const accounts = useMemo(() => accountsFrom(result.data), [result.data]);
  const refresh = async (accountId: string) => {
    if (!window.confirm(t('Обновление тратит немного лимита. Продолжить?'))) return;
    setRefreshing(accountId);
    setNotice('');
    try {
      const response = await api<{ detail?: string }>(`/accounts/${encodeURIComponent(accountId)}/limits/refresh`, {
        method: 'POST',
      });
      setNotice(response?.detail ?? t('Задание на обновление отправлено.'));
      result.reload();
    } catch (cause) {
      setNotice(cause instanceof ApiError ? cause.message : t('Не удалось запустить обновление'));
    } finally {
      setRefreshing(null);
    }
  };
  return (
    <>
      <div className="page-heading limits-heading">
        <div>
          <p className="eyebrow">{t('СИСТЕМА')}</p>
          <h1>{t('Лимиты')}</h1>
          <p className="muted">{t('Использование подписок аккаунтов Claude и Codex.')}</p>
        </div>
        <Link className="ui-button ui-button-secondary" to="/settings/accounts">
          {t('Аккаунты и модели')}
        </Link>
      </div>
      {notice && (
        <p className="limits-notice" role="status">
          {notice}
        </p>
      )}
      {result.error && <ErrorBanner message={result.error} />}
      {result.loading && !result.data ? (
        <Loading />
      ) : accounts.length === 0 ? (
        <section className="panel limits-empty">
          <div className="limits-empty-icon">◌</div>
          <h2>{t('Лимиты появятся после первой сессии на аккаунте')}</h2>
          <p className="muted">{t('Запустите сессию, чтобы worker передал актуальные окна использования.')}</p>
        </section>
      ) : (
        <section className="limits-grid" aria-label={t('Лимиты аккаунтов')}>
          {accounts.map((account) => (
            <article className={`panel limit-card ${account.stale ? 'is-stale' : ''}`} key={account.account_id}>
              <header className="limit-card-header">
                <div>
                  <h2>{account.account_name || account.account_id}</h2>
                  <span className="muted">{account.engine || t('Движок не указан')}</span>
                </div>
                {accountStale(account) && <span className="limit-stale">{t('устарело')}</span>}
              </header>
              <div className="limit-bars">
                {account.windows.map((item) => (
                  <LimitBar item={item} key={item.kind} />
                ))}
              </div>
              <footer className="limit-card-footer">
                <span className="muted">
                  {(() => {
                    const captured = accountCapturedAt(account);
                    return captured
                      ? t(
                          'данные от {0}',
                          captured.toLocaleString([], {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                          }),
                        )
                      : t('данных пока нет');
                  })()}
                </span>
                <button
                  className="ui-button ui-button-secondary"
                  disabled={refreshing === account.account_id}
                  onClick={() => void refresh(account.account_id)}
                >
                  {refreshing === account.account_id ? t('Обновление…') : t('Обновить')}
                </button>
              </footer>
            </article>
          ))}
        </section>
      )}
    </>
  );
}
