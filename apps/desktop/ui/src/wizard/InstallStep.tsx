import { t } from '../i18n';
export function InstallStep() {
  return (
    <>
      <h1>{t('Установка')}</h1>
      <p>{t('Установка воркера и ожидание подключения к хабу…')}</p>
    </>
  );
}
