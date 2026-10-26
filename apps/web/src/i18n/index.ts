// UI translation. Keys are the Russian source strings, so the code stays readable and an untranslated
// string falls back to Russian. Placeholders: t('Найдено {0} заметок', count).
import { en } from './en';

export type Lang = 'ru' | 'en';
const STORAGE_KEY = 'aihub.lang';

function detect(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'ru' || saved === 'en') return saved;
  } catch {
    /* storage is optional */
  }
  return typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('ru') ? 'ru' : 'en';
}

export const lang: Lang = detect();
if (typeof document !== 'undefined') document.documentElement.lang = lang;

export function t(key: string, ...args: unknown[]): string {
  const template = lang === 'en' ? (en[key] ?? key) : key;
  return args.length
    ? template.replace(/\{(\d+)\}/g, (match, index: string) => String(args[Number(index)] ?? match))
    : template;
}

/** Switching reloads the page: module-level labels are computed once, at import. */
export function setLang(next: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* storage is optional */
  }
  window.location.reload();
}
