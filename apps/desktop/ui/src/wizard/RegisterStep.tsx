import type { ExistingWorker } from '../ipc';
import { t } from '../i18n';
export const workerIdPattern = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
export function RegisterStep({
  value,
  onChange,
  existing,
  useExisting,
  onUseExisting,
}: {
  value: string;
  onChange: (value: string) => void;
  existing: ExistingWorker | null;
  useExisting: boolean;
  onUseExisting: (use: boolean) => void;
}) {
  const invalid = value.length > 0 && !workerIdPattern.test(value);
  return (
    <>
      <h1>{t('Регистрация')}</h1>
      {existing && (
        <div className="choice" role="radiogroup" aria-label={t('Воркер этой машины')}>
          <label className="check">
            <input type="radio" checked={useExisting} onChange={() => onUseExisting(true)} />
            <span>
              <strong>
                {t('Использовать подключённый воркер')} «{existing.workerId}»
              </strong>
              <small className="muted">
                {existing.active
                  ? t(
                      'Служба aihub-worker уже работает с этим хабом. Приложение будет следить за ней, ничего не устанавливая.',
                    )
                  : t(
                      'Служба aihub-worker найдена, но сейчас не запущена. Приложение будет следить за ней, ничего не устанавливая.',
                    )}
              </small>
            </span>
          </label>
          <label className="check">
            <input type="radio" checked={!useExisting} onChange={() => onUseExisting(false)} />
            <span>
              <strong>{t('Новый воркер')}</strong>
              <small className="muted">{t('Второй воркер на этой машине, со своей службой и токеном.')}</small>
            </span>
          </label>
        </div>
      )}
      {!(existing && useExisting) && (
        <>
          <p className="muted">{t('ID воркера должен быть уникальным.')}</p>
          <label>
            Worker ID
            <input
              aria-label="Worker ID"
              value={value}
              onChange={(event) => onChange(event.target.value.toLowerCase())}
            />
          </label>
          {invalid && <small className="error-text">{t('desktop.err.invalid_worker_id')}</small>}
        </>
      )}
    </>
  );
}
