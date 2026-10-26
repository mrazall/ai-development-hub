import { useMemo, useState } from 'react';
import type { Project, Session } from '../api/types';
import { useApi } from '../api/useApi';
import { StatusIcon, StatusLegend } from './ui';
import { t } from '../i18n';

/** Each project's status from its sessions: any running → running; else the latest failed → failed; else done. */
export function useProjectStatus(): Map<string, string> {
  const allSessions = useApi<Session[]>('/sessions?limit=1000', { refreshMs: 10_000 });
  return useMemo(() => {
    const byProject = new Map<string, Session[]>();
    for (const item of allSessions.data ?? [])
      byProject.set(item.project_id, [...(byProject.get(item.project_id) ?? []), item]);
    const result = new Map<string, string>();
    byProject.forEach((items, id) => {
      const latest = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
      if (items.some((item) => ['running', 'starting', 'queued'].includes(item.status))) result.set(id, 'running');
      else if (['failed', 'offline', 'blocked'].includes(latest.status)) result.set(id, 'failed');
      else if (latest.status === 'completed') result.set(id, 'completed');
      else result.set(id, latest.status);
    });
    return result;
  }, [allSessions.data]);
}

/** The projects panel of Workspace and Agents: legend, search, rows with a status icon. */
export function ProjectList({
  projects,
  status,
  selected,
  onSelect,
}: {
  projects: Project[];
  status: Map<string, string>;
  selected: string;
  onSelect: (id: string) => void;
}): JSX.Element {
  const [query, setQuery] = useState('');
  const filtered = projects.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="sidebar-section">
      <div className="panel-heading">
        <h2>{t('Проекты')}</h2>
        <span className="muted">{projects.length}</span>
      </div>
      <StatusLegend />
      <input
        aria-label={t('Поиск проектов')}
        placeholder={t('Поиск…')}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {filtered.map((item) => (
        <button
          className={`project-list-item ${selected === item.id ? 'selected' : ''}`}
          key={item.id}
          onClick={() => onSelect(item.id)}
        >
          <span>
            <strong>{item.name}</strong>
            <small title={item.id}>{item.id}</small>
          </span>
          <StatusIcon value={status.get(item.id) ?? 'idle'} />
        </button>
      ))}
    </div>
  );
}
