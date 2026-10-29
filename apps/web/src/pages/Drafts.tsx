import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useApi } from '../api/useApi';
import { MarkdownView } from '../components/MarkdownView';
import { ConfirmDialog, EmptyState, ErrorBanner, Loading, StatusIcon } from '../components/ui';
import { Icon } from '../components/ui/icons';
import { t } from '../i18n';
import { TimeAgo } from '../components/time';

type DraftSession = { id: string; status: string; title: string; project_id: string };
type Draft = {
  id: string;
  project_id: string;
  name: string;
  title: string;
  kind: string;
  status: 'new' | 'applied' | 'dismissed';
  created_at?: string | null;
  preview?: string;
  session: DraftSession | null;
};
type DraftList = { items: Draft[]; apply_available: boolean };
type Action = { kind: 'apply' | 'revert' | 'dismiss' | 'restore'; draft: Draft };

const FILTERS = [
  ['new', t('Новые')],
  ['applied', t('Внесённые')],
  ['dismissed', t('Отклонённые')],
] as const;

const draftPath = (draft: Draft) =>
  `/knowledge/drafts/${encodeURIComponent(draft.project_id)}/${encodeURIComponent(draft.name)}`;
const sessionBusy = (draft: Draft) => ['queued', 'starting', 'running'].includes(draft.session?.status ?? '');

export function Drafts(): JSX.Element {
  const list = useApi<DraftList>('/knowledge/drafts', { refreshMs: 15_000 });
  const [filter, setFilter] = useState<Draft['status']>('new');
  const [open, setOpen] = useState<string | null>(null);
  const [pending, setPending] = useState<Action | null>(null);
  const [error, setError] = useState('');
  const items = (list.data?.items ?? []).filter((item) => item.status === filter);
  const counts = Object.fromEntries(
    FILTERS.map(([value]) => [value, (list.data?.items ?? []).filter((item) => item.status === value).length]),
  );
  const run = async () => {
    if (!pending) return;
    setError('');
    try {
      await api(`${draftPath(pending.draft)}/${pending.kind}`, { method: 'POST' });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t('Действие не выполнено'));
    } finally {
      setPending(null);
    }
  };
  const confirmText: Record<Action['kind'], [string, string, string]> = {
    apply: [
      t('Внести черновик в базу?'),
      t(
        'Sonnet 5.5 разнесёт черновик по заметкам базы на вашем ПК и сделает git-коммит. Ход работы — в сессии; отменить можно кнопкой «Откатить».',
      ),
      t('Внести'),
    ],
    revert: [
      t('Откатить внесение?'),
      t('Sonnet сделает git revert коммита с этим черновиком; ваши собственные правки не затрагиваются.'),
      t('Откатить'),
    ],
    dismiss: [t('Отклонить черновик?'), t('Файл останется в папке _Агенты со статусом «отклонён».'), t('Отклонить')],
    restore: [t('Вернуть в новые?'), t('Черновик снова появится среди новых.'), t('Вернуть')],
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ПАМЯТЬ')}</p>
          <h1>{t('Черновики агентов')}</h1>
          <p className="muted">
            {t('Что агенты предлагают сохранить в базу знаний. Файлы лежат в папке')} <code>_Агенты</code>{' '}
            {t('и в поиск не попадают, пока вы их не внесёте.')}
          </p>
        </div>
      </div>
      <div className="segmented drafts-filter" role="tablist" aria-label={t('Статус черновиков')}>
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={filter === value}
            className={filter === value ? 'active' : ''}
            onClick={() => setFilter(value)}
          >
            {label} <span className="muted">{counts[value] ?? 0}</span>
          </button>
        ))}
      </div>
      {list.data && !list.data.apply_available && (
        <p className="muted">{t('Внесение в базу не настроено на сервере: доступны просмотр и отклонение.')}</p>
      )}
      {(error || list.error) && <ErrorBanner message={error || list.error} />}
      {list.loading && !list.data ? (
        <Loading />
      ) : !items.length ? (
        <EmptyState title={t('Пусто')}>
          {filter === 'new' ? t('Новых черновиков нет: агенты ещё ничего не предложили.') : t('Здесь пока ничего нет.')}
        </EmptyState>
      ) : (
        <ul className="drafts-list">
          {items.map((draft) => (
            <li key={draft.id} className="panel draft-card">
              <div className="draft-head">
                <button className="draft-title" onClick={() => setOpen(open === draft.id ? null : draft.id)}>
                  <Icon name={open === draft.id ? 'down' : 'expand'} size={16} />
                  <strong>{draft.title}</strong>
                </button>
                <small className="muted">
                  {draft.project_id} · {draft.created_at ? <TimeAgo value={draft.created_at} /> : draft.name}
                </small>
              </div>
              {open === draft.id ? (
                <DraftBody draft={draft} />
              ) : (
                draft.preview && <p className="draft-preview">{draft.preview}</p>
              )}
              <div className="draft-actions">
                {draft.session && (
                  <Link
                    className="draft-session"
                    to={`/workspace?project=${encodeURIComponent(draft.session.project_id)}&session=${draft.session.id}`}
                  >
                    <StatusIcon value={draft.session.status} />
                    {draft.session.title}
                  </Link>
                )}
                <span className="draft-buttons">
                  {draft.status === 'new' && (
                    <>
                      <button
                        className="button-secondary"
                        onClick={() => setPending({ kind: 'dismiss', draft })}
                        disabled={sessionBusy(draft)}
                      >
                        {t('Отклонить')}
                      </button>
                      <button
                        onClick={() => setPending({ kind: 'apply', draft })}
                        disabled={!list.data?.apply_available || sessionBusy(draft)}
                      >
                        {sessionBusy(draft) ? t('Вносится…') : t('Внести в базу')}
                      </button>
                    </>
                  )}
                  {draft.status === 'applied' && (
                    <button
                      className="button-secondary"
                      onClick={() => setPending({ kind: 'revert', draft })}
                      disabled={!list.data?.apply_available || sessionBusy(draft)}
                    >
                      {sessionBusy(draft) ? t('Откатывается…') : t('Откатить')}
                    </button>
                  )}
                  {draft.status === 'dismissed' && (
                    <button className="button-secondary" onClick={() => setPending({ kind: 'restore', draft })}>
                      {t('Вернуть в новые')}
                    </button>
                  )}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={Boolean(pending)}
        title={pending ? confirmText[pending.kind][0] : ''}
        description={pending ? confirmText[pending.kind][1] : ''}
        confirmLabel={pending ? confirmText[pending.kind][2] : ''}
        danger={pending?.kind === 'revert'}
        onClose={() => setPending(null)}
        onConfirm={() => void run()}
      />
    </>
  );
}

function DraftBody({ draft }: { draft: Draft }): JSX.Element {
  const full = useApi<{ content: string }>(draftPath(draft));
  if (full.error) return <ErrorBanner message={full.error} />;
  if (!full.data) return <Loading />;
  return (
    <div className="draft-body">
      <MarkdownView content={full.data.content} />
    </div>
  );
}
