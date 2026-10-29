import { useCallback, useEffect, useRef, useState } from 'react';
import { api, changedEvent } from './client';
import { t } from '../i18n';

export type Loadable<T> = { data: T | null; error: string; loading: boolean; reload: () => void };
const EMPTY_ARRAY: never[] = [];

/** Keep list screens usable when an older/partial API response omits a collection. */
export function arrayOrEmpty<T>(value: T[] | null | undefined): T[];
export function arrayOrEmpty<T>(value: unknown): T[];
export function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? value : (EMPTY_ARRAY as T[]);
}

/**
 * GET `path` (or skip when null); re-fetches when the path changes, on `reload()`, after any write made
 * through `api()` anywhere in the app, and — with `refreshMs` — periodically and when the tab is shown again.
 */
export function useApi<T>(path: string | null, options: { refreshMs?: number } = {}): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(path !== null);
  const [generation, setGeneration] = useState(0);
  const shown = useRef<string | null>(null);
  const reload = useCallback(() => setGeneration((value) => value + 1), []);
  const { refreshMs } = options;

  useEffect(() => {
    if (path === null) return undefined;
    window.addEventListener(changedEvent, reload);
    let timer: number | undefined;
    const onVisible = () => {
      if (document.visibilityState === 'visible') reload();
    };
    if (refreshMs) {
      timer = window.setInterval(() => {
        if (document.visibilityState === 'visible') reload();
      }, refreshMs);
      document.addEventListener('visibilitychange', onVisible);
    }
    return () => {
      window.removeEventListener(changedEvent, reload);
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [path, refreshMs, reload]);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    // A background refresh of what is already on screen must not flash "loading".
    if (shown.current !== path) setLoading(true);
    api<T>(path)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError('');
          shown.current = path;
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : t('Не удалось загрузить данные'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, generation]);

  return { data, error, loading, reload };
}

export function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/** "N с назад" / "N мин назад" for timestamps from the API. */
export function ago(timestamp: string | null | undefined): string {
  if (!timestamp) return t('никогда');
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 60) return t('{0} с назад', seconds);
  if (seconds < 3600) return t('{0} мин назад', Math.round(seconds / 60));
  if (seconds < 86400) return t('{0} ч назад', Math.round(seconds / 3600));
  return new Date(timestamp).toLocaleString();
}
