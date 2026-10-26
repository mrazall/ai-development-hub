import { useEffect, useState } from 'react';
import { api, logout, tokenKey } from '../api/client';

export type User = { id: string; username: string; role: 'admin' | 'viewer' };

export function useCurrentUser(): User | null {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    const handleLogout = () => setUser(null);
    window.addEventListener('unauthorized', handleLogout);
    if (sessionStorage.getItem(tokenKey)) void api<User>('/auth/me').then(setUser).catch(handleLogout);
    return () => window.removeEventListener('unauthorized', handleLogout);
  }, []);
  return user;
}

export { logout, tokenKey };
