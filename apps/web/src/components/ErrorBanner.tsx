import { t } from '../i18n';
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }): JSX.Element {
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="button-secondary" onClick={onRetry}>
          {t('Повторить')}
        </button>
      )}
    </div>
  );
}
