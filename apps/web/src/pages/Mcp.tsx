import { useState } from 'react';
import { api } from '../api/client';
import { errorText, useApi } from '../api/useApi';
import type { McpServer, Project } from '../api/types';
import type { User } from '../auth/session';
import { Dialog, EmptyState, ErrorBanner, Loading, StatusIcon, StatusLegend } from '../components/ui';
import { t } from '../i18n';

export function Mcp({ user }: { user: User }): JSX.Element {
  const servers = useApi<McpServer[]>('/mcp');
  const projects = useApi<Project[]>('/projects');
  const [config, setConfig] = useState<string | null>(null);
  const [configError, setConfigError] = useState('');
  const missing = servers.error.includes('(404)');
  const toggle = async (server: McpServer) => {
    await api(`/mcp/${server.id}/${server.enabled ? 'disable' : 'enable'}`, { method: 'POST' });
    servers.reload();
  };
  const check = async (server: McpServer) => {
    await api(`/mcp/${server.id}/check`, { method: 'POST' });
    servers.reload();
  };
  const showConfig = async (projectId: string, engine: string) => {
    try {
      const result = await api<unknown>(
        `/mcp/config?project_id=${encodeURIComponent(projectId)}&engine=${encodeURIComponent(engine)}`,
      );
      setConfig(JSON.stringify(result, null, 2));
      setConfigError('');
    } catch (cause) {
      setConfigError(errorText(cause, t('Не удалось получить конфигурацию')));
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('НАСТРОЙКИ')}</p>
          <h1>{t('MCP-серверы')}</h1>
          <p className="muted">{t('Разрешения и конфигурации выдаются проектам с минимальными правами.')}</p>
        </div>
      </div>
      <StatusLegend items={MCP_LEGEND} />
      {missing ? (
        <div className="notice">
          <strong>{t('Бэкенд MCP ещё не подключён')}</strong>
          <span>{t('API `/mcp` пока не зарегистрирован. Фейковые данные не показываются.')}</span>
        </div>
      ) : servers.error ? (
        <ErrorBanner message={servers.error} />
      ) : null}
      {!missing && !servers.data ? <Loading /> : null}
      {!missing && servers.data?.length === 0 ? <EmptyState>{t('Доступных MCP-серверов пока нет.')}</EmptyState> : null}
      <div className="mcp-grid">
        {servers.data?.map((server) => (
          <McpCard
            key={server.id}
            server={server}
            admin={user.role === 'admin'}
            onToggle={() => toggle(server)}
            onCheck={() => check(server)}
            onConfig={showConfig}
            projects={projects.data ?? []}
          />
        ))}
      </div>
      {configError && <ErrorBanner message={configError} />}
      {config && (
        <Dialog open title={t('Конфигурация для проекта')} onClose={() => setConfig(null)}>
          <section>
            <div className="panel-heading">
              <span className="muted">{t('Скопируйте конфигурацию в настройки движка.')}</span>
            </div>
            <pre className="document">{config}</pre>
            <button onClick={() => navigator.clipboard.writeText(config)}>{t('Скопировать конфигурацию')}</button>
          </section>
        </Dialog>
      )}
    </>
  );
}

// Hub-side check: an HTTP server is probed from the hub; a stdio server starts only on a worker, so the
// hub cannot see it and it stays "not checked".
const MCP_STATUS: Record<string, string> = {
  ok: t('доступен'),
  error: t('ошибка проверки'),
  unknown: t('не проверялся хабом'),
};
const MCP_LEGEND: [string, string][] = [
  ['ok', MCP_STATUS.ok],
  ['error', MCP_STATUS.error],
  ['unknown', MCP_STATUS.unknown],
];

function McpCard({
  server,
  admin,
  onToggle,
  onCheck,
  onConfig,
  projects,
}: {
  server: McpServer;
  admin: boolean;
  onToggle: () => void;
  onCheck: () => void;
  onConfig: (projectId: string, engine: string) => void;
  projects: Project[];
}): JSX.Element {
  const [project, setProject] = useState(projects[0]?.id ?? '');
  const [engine, setEngine] = useState('claude_code');
  const checkedAt = (server as McpServer & { checked_at?: string | null }).checked_at;
  return (
    <article className="panel mcp-card">
      <div className="card-top">
        <div>
          <h2>{server.name}</h2>
          <p className="muted">
            {server.source} · v{server.version} · {server.license}
          </p>
        </div>
        <StatusIcon value={server.status} label={MCP_STATUS[server.status] ?? server.status} />
      </div>
      <dl>
        <dt>{t('Транспорт')}</dt>
        <dd>
          {server.transport}
          {server.url ? ` · ${server.url}` : ''}
        </dd>
        <dt>{t('Разрешения')}</dt>
        <dd>{server.scopes.length ? server.scopes.join(', ') : t('не заданы')}</dd>
        <dt>{t('Проекты')}</dt>
        <dd>{server.project_ids.length ? server.project_ids.join(', ') : t('не назначены')}</dd>
        <dt>{t('Инструменты')}</dt>
        <dd>{server.tools.length ? server.tools.join(', ') : t('не обнаружены')}</dd>
        <dt>{t('Последняя проверка')}</dt>
        <dd>{checkedAt ? new Date(checkedAt).toLocaleString() : t('ещё не выполнялась')}</dd>
      </dl>
      {server.status_detail && <p className="muted">{server.status_detail}</p>}
      <div className="card-actions">
        {admin && <button onClick={onToggle}>{server.enabled ? t('Выключить') : t('Включить')}</button>}
        {admin && (
          <button className="button-secondary" onClick={onCheck}>
            {t('Проверить')}
          </button>
        )}
        <select
          aria-label={t('Проект для конфигурации')}
          value={project}
          onChange={(event) => setProject(event.target.value)}
        >
          <option value="">{t('Проект…')}</option>
          {projects.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t('Движок конфигурации')}
          value={engine}
          onChange={(event) => setEngine(event.target.value)}
        >
          <option value="claude_code">Claude Code</option>
          <option value="codex">Codex</option>
        </select>
        <button className="button-secondary" disabled={!project} onClick={() => onConfig(project, engine)}>
          {t('Конфигурация для проекта')}
        </button>
      </div>
    </article>
  );
}
