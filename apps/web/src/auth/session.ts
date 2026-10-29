import { useEffect, useState } from 'react';
import { api, logout, refreshSession, tokenKey } from '../api/client';

export type User = { id: string; username: string; role: 'admin' | 'viewer' };
export type SessionState = { user: User | null; signedOut: boolean };

/** The signed-in user; a closed and reopened app is signed in again from the device cookie. */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ user: null, signedOut: false });
  useEffect(() => {
    const handleLogout = () => setState({ user: null, signedOut: true });
    window.addEventListener('unauthorized', handleLogout);
    const signedIn = sessionStorage.getItem(tokenKey) ? Promise.resolve(true) : refreshSession();
    void signedIn
      .then((ok) => (ok ? api<User>('/auth/me').then((user) => setState({ user, signedOut: false })) : handleLogout()))
      .catch(handleLogout);
    return () => window.removeEventListener('unauthorized', handleLogout);
  }, []);
  return state;
}

export function useCurrentUser(): User | null {
  return useSession().user;
}

export { logout, tokenKey };
