import { Link } from 'react-router-dom';
import { ago, useApi } from '../api/useApi';
import { ErrorBanner, Loading, StatusIcon } from '../components/ui';
import { t } from '../i18n';

type Check = {
  key: string;
  title: string;
  status: 'ok' | 'unknown' | 'warning' | 'critical';
  summary: string;
  details: string[];
};
type Report = { status: Check['status']; checked_at: string; checks: Check[] };

// Health status → the site's status icons (green check, red alert, amber warning, hollow = unknown).
const ICON: Record<Check['status'], string> = {
  ok: 'completed',
  warning: 'warning',
  critical: 'failed',
  unknown: 'draft',
};
const LABEL: Record<Check['status'], string> = {
  ok: t('всё в порядке'),
  warning: t('есть предупреждения'),
  critical: t('сбой'),
  unknown: t('нет данных'),
};
// Where to go to fix it.
const LINKS: Record<string, [string, string]> = {
  workers: ['/settings/workers', t('Исполнители')],
  limits: ['/limits', t('Лимиты')],
  knowledge: ['/knowledge', t('Знания')],
  backups: ['/backups', t('Резервные копии')],
  errors: ['/workspace', t('Рабочая область')],
};

export function Health(): JSX.Element {
  const report = useApi<Report>('/system/health', { refreshMs: 15_000 });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('СИСТЕМА')}</p>
          <h1>{t('Здоровье системы')}</h1>
          <p className="muted">
            {t(
              'Проверки обновляются каждые 15 секунд. О сбоях и восстановлении приходят уведомления, даже если страница закрыта.',
            )}
          </p>
        </div>
        {report.data && (
          <div className="health-overall">
            <StatusIcon value={ICON[report.data.status]} label={LABEL[report.data.status]} />
            <span>{LABEL[report.data.status]}</span>
            <small className="muted">
              {t('проверено')} {ago(report.data.checked_at)}
            </small>
          </div>
        )}
      </div>
      {report.error && <ErrorBanner message={report.error} />}
      {report.loading && !report.data ? (
        <Loading />
      ) : (
        <div className="health-grid">
          {(report.data?.checks ?? []).map((check) => (
            <section key={check.key} className={`panel health-card health-${check.status}`}>
              <header>
                <StatusIcon value={ICON[check.status]} label={LABEL[check.status]} />
                <h2>{t(check.title)}</h2>
              </header>
              <p className="health-summary">{t(check.summary)}</p>
              {check.details.length > 0 && (
                <ul className="health-details">
                  {check.details.map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ul>
              )}
              {LINKS[check.key] && check.status !== 'ok' && (
                <Link className="health-link" to={LINKS[check.key][0]}>
                  {t('Перейти:')} {LINKS[check.key][1]}
                </Link>
              )}
            </section>
          ))}
        </div>
      )}
    </>
  );
}
