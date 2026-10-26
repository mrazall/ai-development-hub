import { useSearchParams } from 'react-router-dom';
import { AgentGraph } from '../components/AgentGraph';
import type { Project } from '../api/types';
import { useApi } from '../api/useApi';
import { ProjectList, useProjectStatus } from '../components/ProjectPicker';
import { SplitPane } from '../components/ui';
import { t } from '../i18n';

export function Agents(): JSX.Element {
  const [params, setParams] = useSearchParams();
  const projects = useApi<Project[]>('/projects');
  const projectStatus = useProjectStatus();
  const projectId = params.get('project') ?? projects.data?.[0]?.id ?? '';
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ОРКЕСТРАЦИЯ')}</p>
          <h1>{t('Агенты')}</h1>
          <p className="muted">{t('Сессии, задачи и связи родитель → ребёнок.')}</p>
        </div>
      </div>
      {/* The same projects panel as in Workspace: status icons, search, foldable. */}
      <SplitPane
        className="workspace-grid agents-grid"
        initial={300}
        min={240}
        max={460}
        storageKey="aihub.agents.projects"
        collapsible
        collapsedLabel={t('Проекты')}
      >
        <aside className="panel workspace-sidebar">
          <ProjectList
            projects={projects.data ?? []}
            status={projectStatus}
            selected={projectId}
            onSelect={(id) => setParams(id ? { project: id } : {})}
          />
        </aside>
        <section className="panel">
          <AgentGraph projectId={projectId} />
        </section>
      </SplitPane>
    </>
  );
}
