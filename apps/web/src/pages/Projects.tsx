import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { User } from '../auth/session';
import {
  Button,
  Dialog,
  EmptyState,
  ErrorBanner,
  Input,
  Select,
  Table,
  Textarea,
  StatusBadge,
  Loading,
} from '../components/ui';
import { ProjectLifecycleToast } from '../components/ProjectLifecycle';
import { t } from '../i18n';

type Project = {
  id: string;
  name: string;
  visibility: string;
  repo_url?: string | null;
  allowed_paths: string[];
  allowed_commands: string[];
  sessions?: number;
  updated_at?: string;
};
type ProjectSort = 'name' | 'updated_at' | 'sessions';
const projectIdPattern = /^[a-z0-9][a-z0-9-]{1,62}$/;
const initialForm = {
  id: '',
  name: '',
  visibility: 'private',
  repo_url: '',
  access: 'auto' as 'auto' | 'manual',
  allowed_paths: '',
  allowed_commands: '',
};
// «Авто»: the agent works only inside the project folder on the worker's machine.
const autoPath = (id: string) => `~/projects/${id || '<id>'}`;
const lines = (value: string) =>
  value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

export function Projects({ user }: { user: User }): JSX.Element {
  const [items, setItems] = useState<Project[]>([]);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<'active' | 'archived' | 'trash'>('active');
  const [dialog, setDialog] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<ProjectSort>('updated_at');
  const [descending, setDescending] = useState(true);
  const canWrite = user.role === 'admin';
  const load = () => {
    setLoading(true);
    void api<Project[]>(`/projects?view=${status}`)
      .then((result) => {
        setItems(result);
        setError('');
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : t('Не удалось загрузить проекты')))
      .finally(() => setLoading(false));
  };
  useEffect(load, [status]);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const result = items.filter((item) =>
      `${item.name} ${item.id} ${item.repo_url ?? ''}`.toLowerCase().includes(normalized),
    );
    return result.sort((left, right) => {
      const a = sort === 'name' ? left.name : sort === 'sessions' ? (left.sessions ?? -1) : (left.updated_at ?? '');
      const b = sort === 'name' ? right.name : sort === 'sessions' ? (right.sessions ?? -1) : (right.updated_at ?? '');
      const comparison = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b));
      return descending ? -comparison : comparison;
    });
  }, [items, query, sort, descending]);
  const sortBy = (next: ProjectSort) => {
    if (sort === next) setDescending((value) => !value);
    else {
      setSort(next);
      setDescending(next !== 'name');
    }
  };
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!projectIdPattern.test(form.id)) return;
    try {
      const project = await api<Project>('/projects', {
        method: 'POST',
        body: JSON.stringify({
          id: form.id,
          name: form.name,
          visibility: form.visibility,
          repo_url: form.repo_url,
          allowed_paths: form.access === 'auto' ? [autoPath(form.id)] : lines(form.allowed_paths),
          allowed_commands: form.access === 'auto' ? [] : lines(form.allowed_commands),
        }),
      });
      setItems((current) => [...current, project]);
      setForm(initialForm);
      setDialog(false);
      setError('');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t('Не удалось создать проект'));
    }
  };
  return (
    <>
      <ProjectLifecycleToast />
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('КАТАЛОГ')}</p>
          <h1>{t('Проекты')}</h1>
          <p className="muted">{t('Все рабочие пространства в одном списке.')}</p>
        </div>
        {canWrite && <Button onClick={() => setDialog(true)}>{t('+ Новый проект')}</Button>}
      </div>
      {error && <ErrorBanner message={error} onRetry={load} />}
      <section className="panel projects-panel">
        <div className="projects-toolbar">
          <div className="project-tabs" role="tablist">
            {(['active', 'archived', 'trash'] as const).map((item) => (
              <button
                key={item}
                className={status === item ? 'active' : ''}
                role="tab"
                aria-selected={status === item}
                onClick={() => setStatus(item)}
              >
                {item === 'active' ? t('Активные') : item === 'archived' ? t('Архив') : t('Корзина')}
              </button>
            ))}
          </div>
          <Input
            aria-label={t('Поиск проектов')}
            placeholder={t('Поиск по названию, ID или репозиторию')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <label className="table-sort-control">
            {t('Сортировать')}
            <Select value={sort} onChange={(event) => sortBy(event.target.value as ProjectSort)}>
              <option value="updated_at">{t('по обновлению')}</option>
              <option value="name">{t('по названию')}</option>
              <option value="sessions">{t('по сессиям')}</option>
            </Select>
          </label>
        </div>
        {loading ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={query ? t('Ничего не найдено') : t('Проектов пока нет')}
            action={
              canWrite && !query && status === 'active' ? (
                <Button onClick={() => setDialog(true)}>{t('Создать проект')}</Button>
              ) : undefined
            }
          >
            {t('Измените фильтр или создайте новое рабочее пространство.')}
          </EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>
                  <button className="table-sort-button" onClick={() => sortBy('name')}>
                    {t('Название')}
                  </button>
                </th>
                <th>ID</th>
                <th>{t('Видимость')}</th>
                <th>{t('Репозиторий')}</th>
                <th>
                  <button className="table-sort-button" onClick={() => sortBy('sessions')}>
                    {t('Сессии')}
                  </button>
                </th>
                <th>
                  <button className="table-sort-button" onClick={() => sortBy('updated_at')}>
                    {t('Обновлён')}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((project) => (
                <tr
                  key={project.id}
                  className="table-row-link"
                  tabIndex={0}
                  onClick={() => (window.location.href = `/projects/${project.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') window.location.href = `/projects/${project.id}`;
                  }}
                >
                  <td>
                    <Link to={`/projects/${project.id}`}>{project.name}</Link>
                  </td>
                  <td title={project.id} className="truncate-cell">
                    {project.id}
                  </td>
                  <td>
                    <StatusBadge value={project.visibility} />
                  </td>
                  <td title={project.repo_url ?? ''} className="truncate-cell">
                    {project.repo_url || '—'}
                  </td>
                  <td>{project.sessions ?? '—'}</td>
                  <td>{project.updated_at ? new Date(project.updated_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>
      <Dialog open={dialog} title={t('Создать проект')} onClose={() => setDialog(false)}>
        <form className="create-form" onSubmit={create}>
          <label>
            {t('ID проекта')}
            <Input value={form.id} onChange={(event) => setForm({ ...form, id: event.target.value })} required />
          </label>
          <small>{t('От 2 до 63 символов: a-z, 0-9 и дефис.')}</small>
          <label>
            {t('Название')}
            <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required />
          </label>
          <label>
            {t('Видимость')}
            <Select value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value })}>
              <option value="private">private</option>
              <option value="shared">shared</option>
              <option value="public">public</option>
            </Select>
          </label>
          <label>
            Repo URL
            <Input value={form.repo_url} onChange={(event) => setForm({ ...form, repo_url: event.target.value })} />
          </label>
          <fieldset className="access-mode">
            <legend>{t('Доступ агента')}</legend>
            <div className="segmented" role="radiogroup" aria-label={t('Доступ агента')}>
              {(
                [
                  ['auto', t('Авто')],
                  ['manual', t('Вручную')],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={form.access === value}
                  className={form.access === value ? 'active' : ''}
                  onClick={() => setForm({ ...form, access: value })}
                >
                  {label}
                </button>
              ))}
            </div>
            {form.access === 'auto' ? (
              <small className="muted">
                {t('Агент работает только в папке')} <code>{autoPath(form.id)}</code>{' '}
                {t('на компьютере с worker-ом. Папка создастся автоматически, вручную создавать не нужно.')}
              </small>
            ) : (
              <>
                <label>
                  {t('Папки, где агенту можно работать')}
                  <Textarea
                    value={form.allowed_paths}
                    placeholder={'~/projects/my-app\n~/code/another'}
                    onChange={(event) => setForm({ ...form, allowed_paths: event.target.value })}
                  />
                </label>
                <small className="muted">
                  {t(
                    'По одной папке на строку. Агент не выйдет за их пределы. Первая папка создастся автоматически, если она внутри ~/projects.',
                  )}
                </small>
                <label>
                  {t('Разрешённые команды (необязательно)')}
                  <Textarea
                    value={form.allowed_commands}
                    placeholder={'npm test\npytest'}
                    onChange={(event) => setForm({ ...form, allowed_commands: event.target.value })}
                  />
                </label>
              </>
            )}
          </fieldset>
          <div className="ui-dialog-actions">
            <Button variant="secondary" type="button" onClick={() => setDialog(false)}>
              {t('Отмена')}
            </Button>
            <Button type="submit" disabled={!projectIdPattern.test(form.id) || !form.name}>
              {t('Создать')}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
