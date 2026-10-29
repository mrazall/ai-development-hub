import { useEffect, useState, useSyncExternalStore } from 'react';
import { ago } from '../api/useApi';
import { t } from '../i18n';

// One timer per interval for the whole page, however many clocks are on screen.
const tickers = new Map<number, { now: number; listeners: Set<() => void>; timer?: number }>();

function subscribe(interval: number, listener: () => void): () => void {
  let ticker = tickers.get(interval);
  if (!ticker) {
    ticker = { now: Date.now(), listeners: new Set() };
    tickers.set(interval, ticker);
  }
  const current = ticker;
  current.listeners.add(listener);
  if (current.timer === undefined) {
    current.timer = window.setInterval(() => {
      current.now = Date.now();
      current.listeners.forEach((notify) => notify());
    }, interval);
  }
  return () => {
    current.listeners.delete(listener);
    if (!current.listeners.size) {
      window.clearInterval(current.timer);
      tickers.delete(interval);
    }
  };
}

/** The current time, re-rendering the caller every `interval` ms. */
export function useNow(interval: number): number {
  return useSyncExternalStore(
    (listener) => subscribe(interval, listener),
    () => tickers.get(interval)?.now ?? Date.now(),
  );
}

/** «5 мин назад» that stays true while the page is open (it used to freeze until a reload). */
export function TimeAgo({ value }: { value: string | null | undefined }): JSX.Element {
  const seconds = value ? (Date.now() - new Date(value).getTime()) / 1000 : Infinity;
  useNow(seconds < 60 ? 5_000 : 30_000);
  return <span title={value ? new Date(value).toLocaleString() : undefined}>{ago(value)}</span>;
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}:${String(total % 60).padStart(2, '0')}` : t('{0} с', total);
}

// Claude Code's spinner glyphs: the star grows and shrinks while the model works.
const GLYPHS = ['·', '✢', '✳', '✶', '✻', '✽', '✻', '✶', '✳', '✢'];

function useReducedMotion(): boolean {
  const query = typeof window !== 'undefined' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const [reduced, setReduced] = useState(Boolean(query?.matches));
  useEffect(() => {
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, [query]);
  return reduced;
}

/**
 * What the agent is doing right now, like Claude Code's «✻ Thinking… (12s)»: an animated glyph, a shimmer
 * over the word and the time since the turn started. Static (no glyph cycling, no shimmer) with reduced motion.
 */
export function Thinking({ label, since }: { label: string; since?: string | number | null }): JSX.Element {
  const reduced = useReducedMotion();
  const now = useNow(reduced ? 1000 : 120);
  const start = since ? new Date(since).getTime() : null;
  const glyph = reduced ? '✻' : GLYPHS[Math.floor(now / 120) % GLYPHS.length];
  return (
    <div className="thinking" role="status" aria-live="polite">
      <span className="thinking-glyph" aria-hidden="true">
        {glyph}
      </span>
      <span className="thinking-word">{label}…</span>
      {start !== null && !Number.isNaN(start) && <span className="thinking-time">{formatElapsed(now - start)}</span>}
    </div>
  );
}
