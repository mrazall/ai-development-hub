import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import type { DeletionImpact } from '../api/types-ops';
import { Toast } from './ui';
import { Icon } from './ui/icons';
import { t } from '../i18n';

type Project = { id: string; name: string; archived_at?: string | null; deleted_at?: string | null };
const pendingToastKey = 'aihub.project-lifecycle-toast';
type PendingToast = { projectId: string; message: string };

function errorText(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 409) {
    return t('Проект нельзя удалить: в нём есть активные сессии. Остановите их в рабочей области и повторите попытку.');
  }
  return cause instanceof Error ? cause.message : t('Операция не выполнена');
}

export function projectStatusLabel(project: Project): string | null {
  if (project.deleted_at) {
    const until = new Date(new Date(project.deleted_at).getTime() + 14 * 24 * 60 * 60 * 1000);
    return t('В корзине до {0}', until.toLocaleDateString('ru-RU'));
  }
  return project.archived_at ? t('В архиве') : null;
}

export function ProjectLifecycleToast(): JSX.Element | null {
  const [pending, setPending] = useState<PendingToast | null>(() => {
    try {
      const value = sessionStorage.getItem(pendingToastKey);
      return value ? (JSON.parse(value) as PendingToast) : null;
    } catch {
      return null;
    }
  });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!pending) return;
    try {
      sessionStorage.removeItem(pendingToastKey);
    } catch {
      /* storage is optional */
    }
  }, [pending]);
  if (!pending && !message) return null;
  if (message) return <Toast message={message} tone="error" onClose={() => setMessage('')} />;
  return (
    <div className="ui-toast ui-toast-success" role="status" aria-live="polite">
      <span>{pending?.message}</span>
      <button
        className="ops-toast-action"
        disabled={busy}
        onClick={() => {
          if (!pending) return;
          setBusy(true);
          void api(`/projects/${pending.projectId}/restore`, { method: 'POST' })
            .then(() => setPending(null))
            .catch((cause) => setMessage(errorText(cause)))
            .finally(() => setBusy(false));
        }}
      >
        {busy ? t('Восстановление…') : t('Восстановить')}
      </button>
      <button className="ops-toast-close" aria-label={t('Закрыть уведомление')} onClick={() => setPending(null)}>
        <Icon name="close" />
      </button>
    </div>
  );
}

export function ProjectLifecycle({
  project,
  onChanged,
}: {
  project: Project;
  onChanged?: (project: Project) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [impact, setImpact] = useState<DeletionImpact | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');
  const navigate = useNavigate();
  const action = async (path: string) => {
    setBusy(true);
    setError('');
    try {
      const result = await api<Project>(`/projects/${project.id}/${path}`, { method: 'POST' });
      onChanged?.(result);
      setToast(path === 'archive' ? t('Проект перемещён в архив') : t('Проект восстановлен'));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };
  const prepareDelete = async () => {
    setOpen(true);
    setError('');
    try {
      setImpact(await api<DeletionImpact>(`/projects/${project.id}/deletion-impact`));
    } catch (cause) {
      setError(errorText(cause));
    }
  };
  const remove = async () => {
    if (name !== project.name) return setError(t('Введите точное название проекта.'));
    setBusy(true);
    try {
      await api(`/projects/${project.id}`, { method: 'DELETE' });
      try {
        sessionStorage.setItem(
          pendingToastKey,
          JSON.stringify({ projectId: project.id, message: t('Проект перемещён в корзину') } satisfies PendingToast),
        );
      } catch {
        /* storage is optional */
      }
      navigate('/projects');
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };
  const status = projectStatusLabel(project);
  return (
    <div className="project-lifecycle" aria-label={t('Жизненный цикл проекта')}>
      {status && <span className="ops-project-status">{status}</span>}
      <button
        className="button-secondary"
        onClick={() => void action(project.archived_at || project.deleted_at ? 'restore' : 'archive')}
        disabled={busy}
      >
        {project.archived_at || project.deleted_at ? t('Восстановить') : t('Архивировать')}
      </button>
      <button
        className="button-danger"
        onClick={() => void prepareDelete()}
        disabled={busy || Boolean(project.deleted_at)}
      >
        {t('Удалить')}
      </button>
      {project.deleted_at && (
        <button className="button-danger" disabled title={t('Удаление навсегда выполнится автоматически')}>
          {t('Удалить навсегда — автоматически через 14 дней')}
        </button>
      )}
      {open && (
        <div className="modal-backdrop" role="presentation">
          <div className="panel modal-body" role="dialog" aria-modal="true" aria-labelledby="delete-title">
            <h2 id="delete-title">{t('Удалить проект?')}</h2>
            {impact && (
              <p>
                {t('Затронет:')} {impact.tasks} {t('задач,')} {impact.sessions} {t('сессий,')} {impact.events}{' '}
                {t('событий,')} {impact.attachments} {t('вложений.')}
              </p>
            )}
            <p className="muted">{t('Репозиторий, файлы, vault и бэкапы не удаляются.')}</p>
            <label>
              {t('Введите название «')}
              {project.name}»
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            {error && !error.includes('активных сессий') && (
              <p className="field-error" role="alert">
                {error}
              </p>
            )}
            {error.includes('активных сессий') && (
              <p className="ops-inline-error" role="alert">
                {error} <Link to="/workspace">{t('Открыть активные сессии')}</Link>
              </p>
            )}
            <div className="modal-actions">
              <button className="button-secondary" onClick={() => setOpen(false)}>
                {t('Отмена')}
              </button>
              <button className="button-danger" onClick={() => void remove()} disabled={busy || name !== project.name}>
                {t('Удалить проект')}
              </button>
            </div>
          </div>
        </div>
      )}
      {toast && <Toast message={toast} onClose={() => setToast('')} />}
    </div>
  );
}
