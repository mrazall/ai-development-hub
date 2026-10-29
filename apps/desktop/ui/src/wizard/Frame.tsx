import type { ReactNode } from 'react';
import { t } from '../i18n';

const steps = ['Хаб', 'Вход', 'Эта машина', 'Движки', 'Регистрация', 'Установка', 'Подписки', 'Готово'];
export function Frame({ children, step }: { children: ReactNode; step?: number }) {
  return (
    <main className="shell">
      <header>
        <NodesMark />
        <span className="brand-name">AI Development Hub</span>
      </header>
      {step !== undefined && (
        <nav aria-label="Wizard progress">
          {steps.map((name, index) => (
            <span className={index === step ? 'current' : index < step ? 'done' : ''} key={name}>
              {index + 1}. {t(name)}
            </span>
          ))}
        </nav>
      )}
      <section className="card">{children}</section>
    </main>
  );
}
export function ErrorBox({
  error,
  errorText,
}: {
  error: AppErrorLike | null;
  errorText: (error: AppErrorLike) => string;
}) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      <strong>{errorText(error)}</strong>
      {/* What actually failed (the hub's or the installer's message): a bare error code says nothing. */}
      {(error.detail || (error.message && error.message !== errorText(error))) && (
        <small>{error.detail || error.message}</small>
      )}
    </div>
  );
}
export type AppErrorLike = { code: string; message: string; detail?: string };

/** The site's logo (apps/web/public/brand/logo-nodes.svg); it was the word «NODES». */
function NodesMark() {
  return (
    <svg className="mark" viewBox="0 0 64 64" role="img" aria-label="AI Development Hub">
      <g stroke="#A6A6A1" strokeWidth="2.5" strokeLinecap="round">
        <line x1="17" y1="25" x2="43" y2="11" />
        <line x1="43" y1="11" x2="46" y2="39" />
        <line x1="17" y1="25" x2="24" y2="49" />
        <line x1="24" y1="49" x2="46" y2="39" />
        <line x1="17" y1="25" x2="46" y2="39" />
      </g>
      <circle cx="43" cy="11" r="7" fill="#F0F0ED" />
      <circle cx="17" cy="25" r="7" fill="#F0F0ED" />
      <circle cx="24" cy="49" r="7" fill="#F0F0ED" />
      <circle cx="46" cy="39" r="9" fill="#E6B85B" />
    </svg>
  );
}
