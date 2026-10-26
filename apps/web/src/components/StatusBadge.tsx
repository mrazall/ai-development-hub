import { t } from '../i18n';
export function StatusBadge({ value: raw }: { value: string | null | undefined }): JSX.Element {
  // Data can arrive later than the component renders: a missing value must never crash the page.
  const value = raw || 'unknown';
  const labels: Record<string, string> = {
    online: t('в сети'),
    offline: t('не в сети'),
    draining: t('выводится'),
    running: t('в работе'),
    queued: t('в очереди'),
    starting: t('запускается'),
    waiting_approval: t('ждёт подтверждения'),
    blocked: t('заблокировано'),
    failed: t('ошибка'),
    completed: t('завершено'),
    pending: t('ожидает'),
    approved: t('разрешено'),
    rejected: t('отклонено'),
    expired: t('истекло'),
    info: t('информация'),
    warning: t('предупреждение'),
    critical: t('критично'),
    admin: t('администратор'),
    viewer: t('только чтение'),
    private: t('личный'),
    shared: t('общий'),
    public: t('публичный'),
    unknown: t('неизвестно'),
  };
  const tone = ['running', 'queued'].includes(value)
    ? 'working'
    : ['online', 'ok', 'completed', 'approved', 'public', 'shared'].includes(value)
      ? 'success'
      : ['failed', 'offline', 'rejected', 'critical'].includes(value)
        ? 'error'
        : ['warning', 'waiting_approval', 'pending', 'starting', 'draining'].includes(value)
          ? 'warning'
          : 'neutral';
  const symbol = { success: '✓', error: '✗', warning: '⚠', working: '●', neutral: '○' }[tone];
  return (
    <span className={`status-badge status-badge-${tone}`}>
      <span aria-hidden="true">{symbol}</span>
      {labels[value] ?? value.replaceAll('_', ' ')}
    </span>
  );
}
