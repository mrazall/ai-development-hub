import { t } from '../i18n';
export function Loading(): JSX.Element {
  return (
    <div className="loading-state" role="status" aria-label={t('Загрузка')}>
      <span className="loading-line" />
      <span className="loading-line loading-line-short" />
    </div>
  );
}
