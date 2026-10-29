import { t } from '../i18n';
export function HubStep({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <>
      <h1>{t('Хаб')}</h1>
      <p className="muted">{t('Укажите адрес хаба. Для localhost разрешён HTTP.')}</p>
      <label>
        {t('Адрес хаба')}
        <input
          aria-label="Hub URL"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="https://hub.example"
        />
      </label>
    </>
  );
}
