import { Component, type ErrorInfo, type ReactNode } from 'react';
import { api } from '../api/client';
import { t } from '../i18n';

// A page that threw used to leave an empty grey screen until a manual reload (seen on phones). Now the error is
// shown with a way out, and its text goes to the hub log so the cause can be found.
const STALE_CHUNK =
  /dynamically imported module|Importing a module script failed|error loading dynamically|ChunkLoadError/i;

export function reportClientError(error: unknown, where: string): void {
  const value = error instanceof Error ? error : new Error(String(error));
  void api('/client-errors', {
    method: 'POST',
    body: JSON.stringify({
      message: value.message.slice(0, 500),
      stack: (value.stack ?? '').slice(0, 4000),
      where,
      path: window.location.pathname,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      user_agent: navigator.userAgent.slice(0, 300),
    }),
  }).catch(() => undefined);
}

/** After a deploy the old page asks for bundle files that no longer exist: one reload fetches the new ones. */
export function reloadOnceForStaleBundle(error: unknown): boolean {
  if (!STALE_CHUNK.test(error instanceof Error ? error.message : String(error))) return false;
  try {
    const last = Number(sessionStorage.getItem('aihub.stale-reload') || 0);
    if (Date.now() - last < 30_000) return false; // already tried: show the error instead of a reload loop
    sessionStorage.setItem('aihub.stale-reload', String(Date.now()));
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

type Props = { children: ReactNode; where: string };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (reloadOnceForStaleBundle(error)) return;
    reportClientError(
      Object.assign(error, { stack: `${error.stack ?? ''}\n${info.componentStack ?? ''}` }),
      this.props.where,
    );
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section className="panel error-boundary" role="alert">
        <h2>{t('Эта страница сломалась')}</h2>
        <p className="muted">{t('Ошибка уже отправлена в журнал хаба. Попробуйте ещё раз или обновите страницу.')}</p>
        <pre>{error.message}</pre>
        <div className="error-boundary-actions">
          <button
            type="button"
            className="ui-button ui-button-secondary"
            onClick={() => this.setState({ error: null })}
          >
            {t('Попробовать ещё раз')}
          </button>
          <button type="button" className="ui-button" onClick={() => window.location.reload()}>
            {t('Обновить страницу')}
          </button>
        </div>
      </section>
    );
  }
}
