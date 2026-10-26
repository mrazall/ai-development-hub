import { t } from '../i18n';
export const tokenKey = 'aihub.access_token';
/** Fired after a successful write; useApi refetches on it. */
export const changedEvent = 'aihub:changed';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
    return body.detail;
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem(tokenKey);
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/api/v0${path}`, { ...init, headers });
  let body: unknown;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (response.status === 401) {
    sessionStorage.removeItem(tokenKey);
    window.dispatchEvent(new Event('unauthorized'));
  }
  if (response.status === 403) throw new ApiError(403, errorMessage(body, t('Нет прав для этой операции')));
  if (response.status === 503) throw new ApiError(503, errorMessage(body, t('Поиск недоступен')));
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, t('Ошибка API ({0})', response.status)));
  const method = (init.method ?? 'GET').toUpperCase();
  // Something changed on the server: let every open view refetch (tickets and logins change nothing visible).
  if (method !== 'GET' && !/^\/(auth\/|events\/stream-ticket)/.test(path))
    window.dispatchEvent(new Event(changedEvent));
  return (response.status === 204 ? undefined : body) as T;
}

export function logout(): void {
  sessionStorage.removeItem(tokenKey);
  window.dispatchEvent(new Event('unauthorized'));
}
