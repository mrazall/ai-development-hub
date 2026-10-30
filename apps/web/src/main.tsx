import { lazy, Suspense, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { useSession } from './auth/session';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { ProjectDetail } from './pages/ProjectDetail';
import { Projects } from './pages/Projects';
import { SessionDetail } from './pages/SessionDetail';
import { Sessions } from './pages/Sessions';
import { Settings } from './pages/Settings';
import { Tasks } from './pages/Tasks';
import { Notifications } from './pages/Notifications';
import { SessionFiles } from './pages/SessionFiles';
import { Workers } from './pages/Workers';
import { Accounts } from './pages/Accounts';
import { Mcp } from './pages/Mcp';
import { Backups } from './pages/Backups';
import { Chats } from './pages/Chats';
import { Limits } from './pages/Limits';
import './style.css';
// Area styles load after the shared sheet so they can refine it without editing it.
import './styles/knowledge-projects.css';
import './styles/settings-mobile.css';
import './styles/page-geometry.css';
import { t } from './i18n';

const Workspace = lazy(() => import('./pages/Workspace').then((module) => ({ default: module.Workspace })));
const Agents = lazy(() => import('./pages/Agents').then((module) => ({ default: module.Agents })));
const Knowledge = lazy(() => import('./pages/Knowledge').then((module) => ({ default: module.Knowledge })));
const Stats = lazy(() => import('./pages/Stats').then((module) => ({ default: module.Stats })));
const SystemSettings = lazy(() =>
  import('./pages/SystemSettings').then((module) => ({ default: module.SystemSettings })),
);
const Health = lazy(() => import('./pages/Health').then((module) => ({ default: module.Health })));
const Drafts = lazy(() => import('./pages/Drafts').then((module) => ({ default: module.Drafts })));

function PageFallback(): JSX.Element {
  return (
    <div className="page-fallback" role="status">
      <span className="ui-skeleton" />
      <span className="ui-skeleton" />
    </div>
  );
}

function PrivateRoutes(): JSX.Element {
  const { user, signedOut } = useSession();
  if (signedOut) return <Navigate to="/login" replace />;
  if (!user) return <p className="loading-screen">{t('Загрузка профиля…')}</p>;
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<Layout user={user} />}>
          <Route index element={<Dashboard />} />
          <Route path="workspace" element={<Workspace />} />
          <Route path="chats" element={<Chats />} />
          <Route path="chats/:id" element={<Chats />} />
          <Route path="agents" element={<Agents />} />
          <Route path="projects" element={<Projects user={user} />} />
          <Route path="projects/:id" element={<ProjectDetail />} />
          <Route path="tasks" element={<Tasks user={user} />} />
          <Route path="workers" element={<Workers user={user} />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="sessions/:id" element={<SessionDetail />} />
          <Route path="sessions/:id/files" element={<SessionFiles />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="knowledge" element={<Knowledge />} />
          <Route path="knowledge/drafts" element={<Drafts />} />
          <Route path="backups" element={<Backups />} />
          <Route path="health" element={<Health />} />
          <Route path="limits" element={<Limits />} />
          <Route path="stats" element={<Stats />} />
          <Route path="settings" element={<Settings user={user} />} />
          <Route path="settings/accounts" element={<Accounts />} />
          <Route path="settings/mcp" element={<Mcp user={user} />} />
          <Route path="settings/projects" element={<Projects user={user} />} />
          <Route path="settings/workers" element={<Workers user={user} />} />
          <Route path="settings/sessions" element={<Sessions />} />
          <Route path="settings/users" element={<Settings user={user} />} />
          <Route path="settings/system" element={<SystemSettings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function NotFound(): JSX.Element {
  return (
    <>
      <h1>{t('Страница не найдена')}</h1>
      <p className="muted">{t('Проверьте адрес или вернитесь в рабочую область.')}</p>
    </>
  );
}

function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<PrivateRoutes />} />
    </Routes>
  );
}
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);

// Registered from the bundle: the server CSP (script-src 'self') blocks inline scripts in index.html.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => void navigator.serviceWorker.register('/sw.js'));
}
