import { useEffect, useState } from 'react';
import { t } from '../i18n';
import { call, inDesktopApp } from './DesktopApp';

// The Windows app draws the panel without the native title bar: the topbar becomes the title bar (drag
// region, double click maximizes) and carries the window buttons. An older app keeps its native frame
// (is_decorated is true or not permitted), and a browser has no bridge: nothing changes there.
const win = <T,>(command: string) => call<T>(`plugin:window|${command}`, { label: 'main' });

/** True inside the Windows app when its window has no native frame. */
export function useFrameless(): boolean {
  const [frameless, setFrameless] = useState(false);
  useEffect(() => {
    if (!inDesktopApp) return;
    win<boolean>('is_decorated')
      .then((decorated) => setFrameless(!decorated))
      .catch(() => setFrameless(false));
  }, []);
  return frameless;
}

/** Minimize, maximize/restore and close, Windows 11 style, at the right end of the topbar. */
export function WindowControls(): JSX.Element {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    // Snap, double click on the drag region and Win+↑/↓ all resize the window: follow it.
    const sync = () => void win<boolean>('is_maximized').then(setMaximized, () => undefined);
    sync();
    window.addEventListener('resize', sync);
    return () => window.removeEventListener('resize', sync);
  }, []);
  return (
    <div className="window-controls">
      <button
        type="button"
        tabIndex={-1}
        aria-label={t('Свернуть')}
        title={t('Свернуть')}
        onClick={() => void win('minimize')}
      >
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M0 5h10" />
        </svg>
      </button>
      <button
        type="button"
        tabIndex={-1}
        aria-label={maximized ? t('Восстановить') : t('Развернуть')}
        title={maximized ? t('Восстановить') : t('Развернуть')}
        onClick={() => void win('toggle_maximize')}
      >
        <svg viewBox="0 0 10 10" aria-hidden="true">
          {maximized ? <path d="M2.5 2.5V.5h7v7h-2M.5 2.5h7v7h-7z" /> : <path d="M.5.5h9v9h-9z" />}
        </svg>
      </button>
      <button
        type="button"
        tabIndex={-1}
        className="window-close"
        aria-label={t('Закрыть')}
        title={t('Закрыть')}
        onClick={() => void win('close')}
      >
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M.5.5l9 9M9.5.5l-9 9" />
        </svg>
      </button>
    </div>
  );
}
