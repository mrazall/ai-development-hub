import { t } from '../i18n';
export function LoginStep({
  user,
  password,
  onUser,
  onPassword,
}: {
  user: string;
  password: string;
  onUser: (value: string) => void;
  onPassword: (value: string) => void;
}) {
  return (
    <>
      <h1>{t('Вход')}</h1>
      <label>
        {t('Пользователь')}
        <input value={user} onChange={(event) => onUser(event.target.value)} autoComplete="username" />
      </label>
      <label>
        {t('Пароль')}
        <input
          type="password"
          value={password}
          onChange={(event) => onPassword(event.target.value)}
          autoComplete="current-password"
        />
      </label>
    </>
  );
}
