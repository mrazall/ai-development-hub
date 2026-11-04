import { Link, useParams } from 'react-router-dom';
import { useApi } from '../../api/useApi';
import { FolderBrowser } from '../../components/FolderBrowser';
import { t } from '../../i18n';
import { ProjectTabs } from './Repo';

/** The project's folder on its worker: what agents changed, and screenshots they left in .aihub/share. */
export function ProjectFiles(): JSX.Element {
  const { id = '' } = useParams();
  const project = useApi<{ name: string }>(`/projects/${id}`);
  return (
    <div className="project-files-page">
      <div className="page-heading">
        <div>
          <Link to="/projects" className="back-link">
            {t('← Все проекты')}
          </Link>
          <p className="eyebrow">{t('ПРОЕКТ')}</p>
          <h1>{project.data?.name || id}</h1>
          <ProjectTabs id={id} active="files" />
        </div>
      </div>
      <section className="panel project-files-panel">
        <FolderBrowser base={`/projects/${encodeURIComponent(id)}`} rootLabel={t('Папка проекта')} />
      </section>
    </div>
  );
}
