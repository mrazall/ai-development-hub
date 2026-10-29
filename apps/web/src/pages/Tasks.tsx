import { FormEvent, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Project, Task, TaskStatus } from '../api/types';
import { taskStatuses } from '../api/types';
import { errorText, useApi } from '../api/useApi';
import type { User } from '../auth/session';
import { EmptyState, ErrorBanner, Input, Loading, Table, Toolbar } from '../components/ui';
import { t } from '../i18n';
import { TimeAgo } from '../components/time';

export function Tasks({ user }: { user: User }): JSX.Element {
  const [params, setParams] = useSearchParams();
  const projects = useApi<Project[]>('/projects');
  const projectId = params.get('project') ?? projects.data?.[0]?.id ?? null;
  const status = params.get('status') ?? '';
  const query = params.get('q') ?? '';
  const tasks = useApi<Task[]>(projectId ? `/projects/${projectId}/tasks` : null);
  const [actionError, setActionError] = useState('');
  const [sort, setSort] = useState<'updated' | 'title' | 'status'>('updated');
  const canWrite = user.role === 'admin';

  const select = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  const setQuery = (value: string) => select('q', value);

  const changeStatus = async (task: Task, next: TaskStatus) => {
    try {
      await api(`/projects/${task.project_id}/tasks/${task.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: task.title, body: task.body, status: next }),
      });
      setActionError('');
      tasks.reload();
    } catch (cause) {
      setActionError(errorText(cause, t('Не удалось изменить статус')));
    }
  };

  if (projects.loading && !projects.data)
    return (
      <>
        <h1>{t('Задачи')}</h1>
        <Loading />
      </>
    );
  if (projects.error)
    return (
      <>
        <h1>{t('Задачи')}</h1>
        <ErrorBanner message={projects.error} />
      </>
    );
  if (!projects.data?.length) {
    return (
      <>
        <h1>{t('Задачи')}</h1>
        <EmptyState>{t('Нет доступных проектов — задачи живут внутри проекта.')}</EmptyState>
      </>
    );
  }

  const visible = (tasks.data ?? [])
    .filter((task) => !status || task.status === status)
    .filter((task) => `${task.title} ${task.body}`.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((left, right) => {
      if (sort === 'title') return left.title.localeCompare(right.title);
      if (sort === 'status') return left.status.localeCompare(right.status) || left.title.localeCompare(right.title);
      return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
    });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('РАБОТА')}</p>
          <h1>{t('Задачи')}</h1>
        </div>
      </div>
      <Toolbar>
        <label>
          {t('Проект')}
          <select value={projectId ?? ''} onChange={(event) => select('project', event.target.value)}>
            {projects.data.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label className="toolbar-search">
          {t('Поиск')}
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('Название или описание')}
          />
        </label>
        <label>
          {t('Сортировка')}
          <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
            <option value="updated">{t('сначала новые')}</option>
            <option value="title">{t('по названию')}</option>
            <option value="status">{t('по статусу')}</option>
          </select>
        </label>
        <label>
          {t('Статус')}
          <select value={status} onChange={(event) => select('status', event.target.value)}>
            <option value="">{t('все')}</option>
            {taskStatuses.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </label>
      </Toolbar>
      {actionError && <ErrorBanner message={actionError} />}
      <div className="project-layout">
        <section className="panel">
          {tasks.error && <ErrorBanner message={tasks.error} />}
          {tasks.loading && !tasks.data ? (
            <Loading />
          ) : visible.length === 0 ? (
            <EmptyState>{t('Задач с таким фильтром нет.')}</EmptyState>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>{t('Задача')}</th>
                  <th>{t('Статус')}</th>
                  <th>{t('Обновлена')}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <strong>{task.title}</strong>
                      {task.body && <p className="muted clamp">{task.body}</p>}
                    </td>
                    <td>
                      <TaskStatusPicker
                        task={task}
                        readOnly={!canWrite}
                        onChange={(next) => void changeStatus(task, next)}
                      />
                    </td>
                    <td>
                      <TimeAgo value={task.updated_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </section>
        {canWrite && projectId && <NewTask projectId={projectId} onCreated={tasks.reload} />}
      </div>
    </>
  );
}

function NewTask({ projectId, onCreated }: { projectId: string; onCreated: () => void }): JSX.Element {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api(`/projects/${projectId}/tasks`, {
        method: 'POST',
        // Idempotency key: a double click or a retried request does not create a duplicate task.
        body: JSON.stringify({ title, body, status: 'draft', idempotency_key: crypto.randomUUID() }),
      });
      setTitle('');
      setBody('');
      setError('');
      onCreated();
    } catch (cause) {
      setError(errorText(cause, t('Не удалось создать задачу')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel create-form" onSubmit={submit}>
      <h2>{t('Новая задача')}</h2>
      <label>
        {t('Название')}
        <input value={title} onChange={(event) => setTitle(event.target.value)} required />
      </label>
      <label>
        {t('Описание')}
        <textarea value={body} onChange={(event) => setBody(event.target.value)} />
      </label>
      {error && <ErrorBanner message={error} />}
      <button disabled={busy || !title.trim()}>{t('Создать задачу')}</button>
    </form>
  );
}

const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  draft: t('черновик'),
  ready: t('готова'),
  in_progress: t('в работе'),
  review: t('на проверке'),
  done: t('сделана'),
  cancelled: t('отменена'),
};

/** One button per status, each with its colour; the current one is filled. Read-only: only the current one. */
function TaskStatusPicker({
  task,
  readOnly,
  onChange,
}: {
  task: Task;
  readOnly: boolean;
  onChange: (next: TaskStatus) => void;
}): JSX.Element {
  const shown = readOnly ? [task.status] : taskStatuses;
  return (
    <div className="task-status-picker" role="radiogroup" aria-label={t('Статус задачи {0}', task.title)}>
      {shown.map((value) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={task.status === value}
          disabled={readOnly}
          className={`task-status task-status-${value} ${task.status === value ? 'is-current' : ''}`}
          onClick={() => task.status !== value && onChange(value)}
        >
          <span className="task-status-dot" aria-hidden="true" />
          {TASK_STATUS_LABEL[value]}
        </button>
      ))}
    </div>
  );
}
