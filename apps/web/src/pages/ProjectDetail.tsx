import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { ErrorBanner, Loading, StatusBadge, Button } from '../components/ui';
import { ProjectLifecycle } from '../components/ProjectLifecycle';
import { t } from '../i18n';
type Project = {
  id: string;
  name: string;
  visibility: string;
  repo_url?: string;
  allowed_paths: string[];
  allowed_commands: string[];
  archived_at?: string | null;
  deleted_at?: string | null;
};
export function ProjectDetail(): JSX.Element {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState('');
  const load = () => {
    if (!id) return;
    setProject(null);
    setError('');
    void api<Project>(`/projects/${id}`)
      .then(setProject)
      .catch((cause) => setError(cause instanceof Error ? cause.message : t('Проект не найден')));
  };
  useEffect(load, [id]);
  if (error)
    return (
      <section className="page-state">
        <ErrorBanner message={error} onRetry={load} />
        <Button variant="secondary" onClick={() => (window.location.href = '/projects')}>
          {t('Вернуться к проектам')}
        </Button>
      </section>
    );
  if (!project) return <Loading />;
  return (
    <>
      <Link to="/projects" className="back-link">
        {t('← Все проекты')}
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ПРОЕКТ')}</p>
          <h1>{project.name}</h1>
          <p className="muted">{project.id}</p>
        </div>
        <div className="project-detail-actions">
          <StatusBadge value={project.visibility} />
          <ProjectLifecycle
            project={project}
            onChanged={(updated) => setProject((current) => (current ? { ...current, ...updated } : current))}
          />
        </div>
      </div>
      <div className="detail-grid">
        <section className="panel">
          <h2>{t('Настройки')}</h2>
          <dl>
            <dt>{t('Репозиторий')}</dt>
            <dd>{project.repo_url || '—'}</dd>
            <dt>{t('Разрешённые пути')}</dt>
            <dd>
              <ul>{project.allowed_paths?.map((value) => <li key={value}>{value}</li>) || <li>—</li>}</ul>
            </dd>
            <dt>{t('Разрешённые команды')}</dt>
            <dd>
              <ul>{project.allowed_commands?.map((value) => <li key={value}>{value}</li>) || <li>—</li>}</ul>
            </dd>
          </dl>
        </section>
        <section className="panel">
          <h2>{t('Участники')}</h2>
          <p className="muted">{t('Участники проекта управляются через control-plane.')}</p>
        </section>
      </div>
    </>
  );
}
