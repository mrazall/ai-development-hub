import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { eventKinds, useEventStream } from '../api/events';
import type {
  AccountUsage,
  OrchestrationView,
  PlanStep,
  Usage,
  AccountProfile,
  Project,
  Session,
  SessionEvent,
  Task,
  Worker,
  WorkerDetails,
} from '../api/types';
import type { Attachment } from '../api/types-ops';
import { ago, useApi } from '../api/useApi';
import { DeleteSessionButton } from '../components/DeleteSessionButton';
import { ConfirmDialog, Dialog, ErrorBanner, Loading, SplitPane, StatusBadge, StatusIcon } from '../components/ui';
import { Icon } from '../components/ui/icons';
import { ChatComposer } from '../components/ChatComposer';
import { SessionTerminal } from '../components/Terminal';
import { MarkdownView } from '../components/MarkdownView';
import { CopyButton, QuoteSelection } from '../components/copy';
import { AttachmentChips, useSessionAttachments } from '../components/attachments';
import { ProjectList, useProjectStatus } from '../components/ProjectPicker';
import { chatEvents, isPartial, useSessionEvents } from '../api/sessionFeed';
import { t } from '../i18n';

const engines = ['claude_code', 'codex', 'opencode'] as const;
// Built-in engines that need no subscription: offered in a demo deployment.
const MOCK_ENGINES = ['mock_echo_prompt', 'mock_write', 'mock_limit'];
type MobileTab = 'sessions' | 'chat' | 'files';

export function Workspace(): JSX.Element {
  const [params, setParams] = useSearchParams();
  const projectId = params.get('project') ?? '';
  const sessionId = params.get('session') ?? '';
  const projects = useApi<Project[]>('/projects');
  const sessions = useApi<Session[]>(projectId ? `/sessions?project_id=${encodeURIComponent(projectId)}` : null, {
    refreshMs: 10_000,
  });
  const projectStatus = useProjectStatus();
  const tasks = useApi<Task[]>(projectId ? `/projects/${encodeURIComponent(projectId)}/tasks` : null, {
    refreshMs: 10_000,
  });
  const [showDialog, setShowDialog] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>('sessions');
  // Without an explicit choice open the newest top-level session, not an executor folded under it.
  const selectedFromList =
    sessions.data?.find((item) => item.id === sessionId) ??
    sessions.data?.find((item) => item.role !== 'executor') ??
    sessions.data?.[0];
  const live = useEventStream({ sessionId: selectedFromList?.id, limit: 100 });
  const selected = useLiveSession(selectedFromList, live);
  const worker = useApi<WorkerDetails>(selected ? `/workers/${encodeURIComponent(selected.worker_id)}` : null);

  useEffect(() => {
    if (!projectId && projects.data?.[0]) setParams({ project: projects.data[0].id });
  }, [projectId, projects.data, setParams]);
  useEffect(() => {
    if (selected && selected.id !== sessionId) setParams({ project: projectId, session: selected.id });
  }, [projectId, selected, sessionId, setParams]);

  const chooseProject = (id: string) => setParams(id ? { project: id } : {});
  // Executors an orchestrator started sit folded under it; the arrow unfolds them.
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const sessionTree = useMemo(() => {
    const list = sessions.data ?? [];
    const ids = new Set(list.map((item) => item.id));
    const children = new Map<string, Session[]>();
    const roots: Session[] = [];
    list.forEach((item) => {
      if (item.role === 'executor' && item.parent_session_id && ids.has(item.parent_session_id)) {
        children.set(item.parent_session_id, [...(children.get(item.parent_session_id) ?? []), item]);
      } else {
        roots.push(item);
      }
    });
    return { roots, children };
  }, [sessions.data]);
  const toggleGroup = (id: string) =>
    setOpenGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const openSession = (id: string) => {
    setParams({ project: projectId, session: id });
    setMobileTab('chat');
  };
  const renderSession = (item: Session, group?: { count: number; open: boolean }, child = false) => (
    <div
      role="button"
      tabIndex={0}
      className={`session-list-item ${child ? 'session-list-child' : ''} ${selected?.id === item.id ? 'selected' : ''}`}
      key={item.id}
      onClick={() => openSession(item.id)}
      onKeyDown={(event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        openSession(item.id);
      }}
    >
      {group && (
        <button
          type="button"
          className="session-group-toggle"
          aria-expanded={group.open}
          aria-label={group.open ? t('Свернуть исполнителей') : t('Показать исполнителей')}
          title={t('Исполнители: {0}', group.count)}
          onClick={(event) => {
            event.stopPropagation();
            toggleGroup(item.id);
          }}
        >
          <span aria-hidden="true">{group.open ? '▾' : '▸'}</span>
          {group.count}
        </button>
      )}
      <span>
        <strong>{item.title || item.engine}</strong>
        <small>
          {item.model} · {ago(item.updated_at)}
        </small>
      </span>
      <StatusIcon value={item.id === selected?.id ? selected.status : item.status} />
      <DeleteSessionButton
        session={item.id === selected?.id ? selected : item}
        onDeleted={() => {
          if (item.id === selected?.id) setParams({ project: projectId });
          sessions.reload();
        }}
      />
    </div>
  );
  return (
    <>
      <div className="page-heading workspace-heading">
        <div>
          <p className="eyebrow">{t('АГЕНТСКАЯ СРЕДА')}</p>
          <h1>{t('Рабочая область')}</h1>
          <p className="muted">{t('Сессии агентов: вывод, shell, чат и события.')}</p>
        </div>
        <button onClick={() => setShowDialog(true)}>{t('+ Новая сессия')}</button>
      </div>
      {projects.error && <ErrorBanner message={projects.error} />}
      <div className="workspace-tabs" role="tablist" aria-label={t('Раздел рабочей области')}>
        {(
          [
            ['sessions', t('Сессии')],
            ['chat', t('Сессия')],
            ['files', t('Файлы')],
          ] as const
        ).map(([tab, label]) => (
          <button
            key={tab}
            className={mobileTab === tab ? 'active' : ''}
            role="tab"
            aria-selected={mobileTab === tab}
            onClick={() => setMobileTab(tab)}
          >
            {label}
          </button>
        ))}
      </div>
      <SplitPane
        className="workspace-grid"
        mobileTab={mobileTab}
        initial={300}
        min={240}
        max={460}
        storageKey="aihub.workspace.sessions"
        collapsible
        collapsedLabel={t('Проекты и сессии')}
      >
        <aside className="panel workspace-sidebar">
          <ProjectList
            projects={projects.data ?? []}
            status={projectStatus}
            selected={projectId}
            onSelect={chooseProject}
          />
          <div className="sidebar-section">
            <div className="panel-heading">
              <h2>{t('Задачи')}</h2>
              <Link to={projectId ? `/tasks?project=${projectId}` : '/tasks'}>{t('Все')}</Link>
            </div>
            {tasks.loading ? (
              <Loading />
            ) : (
              (tasks.data ?? []).slice(0, 5).map((task) => (
                <div className="workspace-task" key={task.id}>
                  <span>{task.title}</span>
                  <StatusIcon value={task.status} />
                </div>
              ))
            )}
          </div>
          <div className="sidebar-section">
            <div className="panel-heading">
              <h2>{t('Сессии')}</h2>
              <span className="muted">{sessions.data?.length ?? 0}</span>
            </div>
            {sessions.error && <ErrorBanner message={sessions.error} />}
            {sessionTree.roots.map((item) => {
              const kids = sessionTree.children.get(item.id) ?? [];
              const open = openGroups.has(item.id) || kids.some((kid) => kid.id === selected?.id);
              return (
                <div key={item.id} className="session-group">
                  {renderSession(item, kids.length ? { count: kids.length, open } : undefined)}
                  {open && kids.map((kid) => renderSession(kid, undefined, true))}
                </div>
              );
            })}
            {projectId && !sessions.data?.length && <p className="muted">{t('Сессий пока нет.')}</p>}
          </div>
        </aside>
        <main className="workspace-center">
          {selected ? (
            <SessionWorkspace
              session={selected}
              worker={worker.data}
              mobileTab={mobileTab}
              onContinued={(id) => {
                sessions.reload();
                setParams({ project: projectId, session: id });
              }}
            />
          ) : (
            <div className="panel empty-workspace">
              <h2>{t('Выберите сессию слева')}</h2>
              <p className="muted">{t('Или создайте новую, чтобы открыть Codeman или чат событий.')}</p>
              <button onClick={() => setShowDialog(true)}>{t('+ Создать сессию')}</button>
            </div>
          )}
        </main>
      </SplitPane>
      {showDialog && (
        <NewSessionDialog
          projects={projects.data ?? []}
          projectId={projectId}
          onClose={() => setShowDialog(false)}
          onCreated={(session) => {
            setShowDialog(false);
            setParams({ project: session.project_id, session: session.id });
            sessions.reload();
          }}
        />
      )}
    </>
  );
}

function useLiveSession(session: Session | undefined, events: ReturnType<typeof useEventStream>): Session | undefined {
  return useMemo(() => {
    if (!session) return undefined;
    const statusEvent = [...events].reverse().find((event) => event.kind === 'session.status');
    const status = statusEvent?.payload.status;
    const live =
      typeof status === 'string' && statusEvent
        ? { ...session, status: status as Session['status'], updated_at: statusEvent.ts }
        : session;
    // An auto-resume scheduled after the last status change is still pending; a newer status ends it.
    const scheduled = [...events].reverse().find((event) => event.kind === 'session.resume_scheduled');
    if (scheduled && (!statusEvent || scheduled.cursor > statusEvent.cursor))
      return { ...live, resume_at: String(scheduled.payload.resume_at) };
    return statusEvent && live.status !== 'failed' ? { ...live, resume_at: null } : live;
  }, [events, session]);
}

function SessionWorkspace({
  session,
  worker,
  mobileTab,
  onContinued,
}: {
  session: Session;
  worker?: WorkerDetails | null;
  mobileTab: MobileTab;
  onContinued: (sessionId: string) => void;
}): JSX.Element {
  const [busy, setBusy] = useState<'stop' | 'retry' | ''>('');
  const [pendingAction, setPendingAction] = useState<'stop' | 'retry' | ''>('');
  const [error, setError] = useState('');
  const iframeUrl =
    session.workspace_ref && worker?.workspace_url
      ? `${worker.workspace_url.replace(/\/$/, '')}/sessions/${encodeURIComponent(session.workspace_ref)}`
      : '';
  const postAction = async (action: 'stop' | 'retry') => {
    setPendingAction(action);
  };
  const confirmAction = async () => {
    const action = pendingAction;
    setPendingAction('');
    if (!action) return;
    setBusy(action);
    setError('');
    try {
      await api(`/sessions/${session.id}/${action}`, { method: 'POST' });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Операция не выполнена'));
    } finally {
      setBusy('');
    }
  };
  const attachments = useSessionAttachments(session.id);
  return (
    <section className="panel session-workspace">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t('СЕССИЯ')}</p>
          <h2>{session.title || session.engine}</h2>
          <p className="muted">
            {session.project_id} · {session.worker_id} · {session.model}
          </p>
          {attachments.length > 0 && (
            <p className="session-attachments">
              <span className="muted">{t('Вложения:')}</span>
              <AttachmentChips items={attachments} />
            </p>
          )}
        </div>
        <div className="session-actions">
          <StatusBadge value={session.status} />
          <Link className="button-secondary" to={`/sessions/${session.id}/files`}>
            {t('Файлы и diff')}
          </Link>
          {session.status !== 'completed' && session.status !== 'failed' && (
            <button className="button-secondary" onClick={() => void postAction('stop')} disabled={!!busy}>
              {busy === 'stop' ? t('Остановка…') : t('Остановить')}
            </button>
          )}
          {session.resume_at && (
            <>
              <span className="muted" role="status">
                {t('Лимит исчерпан — продолжится сам в')}{' '}
                {new Date(session.resume_at).toLocaleString('ru-RU', {
                  hour: '2-digit',
                  minute: '2-digit',
                  day: 'numeric',
                  month: 'short',
                })}
              </span>
              <button className="button-secondary" onClick={() => void postAction('stop')} disabled={!!busy}>
                {t('Не продолжать')}
              </button>
            </>
          )}
          {(session.status === 'failed' || session.status === 'completed') && (
            <button className="button-secondary" onClick={() => void postAction('retry')} disabled={!!busy}>
              {busy === 'retry' ? t('Повтор…') : t('Повторить')}
            </button>
          )}
          {iframeUrl && (
            <a className="button-secondary" href={iframeUrl} target="_blank" rel="noreferrer">
              {t('Открыть в Codeman')}
            </a>
          )}
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      {worker && (
        <div className="worker-status-card" aria-label={t('Состояние worker')}>
          <StatusBadge value={worker.status} />
          <span>
            <strong>{worker.id}</strong> {t('· последний сигнал')} {ago(worker.last_heartbeat_at)}
          </span>
          <span className="muted">{t('источник: heartbeat')}</span>
        </div>
      )}
      <div className="session-status-line" aria-label={t('Статус сессии')}>
        <StatusBadge value={session.status} />
        <span>
          {t('Длительность:')} {durationLabel(session)}
        </span>
        <span className="muted">
          {t('источник:')}{' '}
          {session.status_source === 'native'
            ? t('нативные события')
            : session.status_source === 'cli_parser'
              ? t('разбор CLI')
              : 'heartbeat'}
        </span>
      </div>
      {/* Agent, Shell, Chat, Events… share one tabbed area so the terminal gets the height. */}
      <div className={`session-tabs-area ${mobileTab === 'files' ? 'workspace-mobile-hidden' : ''}`}>
        <SessionTerminal
          sessionId={session.id}
          extraTabs={[
            { id: 'chat', label: t('Чат'), content: <ChatFeed sessionId={session.id} /> },
            { id: 'events', label: t('События'), content: <SessionEvents sessionId={session.id} /> },
            // Orchestration links: the executors an orchestrator runs, or the parent of an executor.
            ...(session.role
              ? [
                  {
                    id: 'executors',
                    label: t('Исполнители'),
                    content: (
                      <>
                        <SessionTree session={session} />
                        {session.role === 'orchestrator' && <ExecutorPanel session={session} />}
                      </>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </div>
      {mobileTab === 'files' && (
        <div className="panel mobile-files-view">
          <h2>{t('Файлы сессии')}</h2>
          <p className="muted">{t('Просмотр дерева файлов, diff и истории Git доступен в отдельной вкладке.')}</p>
          <Link className="button-secondary" to={`/sessions/${session.id}/files`}>
            {t('Открыть файлы и Git')}
          </Link>
        </div>
      )}
      <ChatComposer
        sessionId={session.id}
        resumable={
          ['claude_code', 'codex'].includes(session.engine) &&
          ['completed', 'failed', 'offline'].includes(session.status)
        }
        onContinued={onContinued}
      />
      <ConfirmDialog
        open={Boolean(pendingAction)}
        title={pendingAction === 'stop' ? t('Остановить сессию?') : t('Повторить сессию?')}
        description={
          pendingAction === 'stop'
            ? t('Агент будет остановлен; ход работы сохранится в журнале.')
            : t('Сессия будет запущена заново с той же задачей.')
        }
        confirmLabel={pendingAction === 'stop' ? t('Остановить') : t('Повторить')}
        danger={pendingAction === 'stop'}
        onClose={() => setPendingAction('')}
        onConfirm={() => void confirmAction()}
      />
    </section>
  );
}

function eventText(event: SessionEvent): string {
  if (typeof event.payload.text === 'string') return event.payload.text;
  if (typeof event.payload.output === 'string') return event.payload.output;
  return JSON.stringify(event.payload, null, 2);
}

function durationLabel(session: Session): string {
  const end = ['completed', 'failed', 'blocked', 'offline'].includes(session.status)
    ? new Date(session.updated_at).getTime()
    : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(session.created_at).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? t('{0} мин {1} с', minutes, seconds % 60) : t('{0} с', seconds);
}

function ChatFeed({ sessionId }: { sessionId: string }): JSX.Element {
  const all = useSessionEvents(sessionId, 200, 'chat');
  const attachments = useSessionAttachments(sessionId);
  // The chat is the conversation: commands and their output live in the Agent and Events tabs.
  const events = useMemo(() => chatEvents(all).filter((event) => !event.kind.startsWith('tool.')), [all]);
  // Like the Claude app: follow new messages while the reader is at the bottom, leave them alone otherwise.
  const feedRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  useEffect(() => {
    const scroller = feedRef.current?.parentElement;
    if (!scroller) return undefined;
    const onScroll = () => {
      pinned.current = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
    };
    scroller.addEventListener('scroll', onScroll);
    return () => scroller.removeEventListener('scroll', onScroll);
  }, []);
  const lastText = events.length ? eventText(events[events.length - 1]).length : 0;
  useEffect(() => {
    const scroller = feedRef.current?.parentElement;
    if (scroller && pinned.current) scroller.scrollTop = scroller.scrollHeight;
  }, [events.length, lastText]);
  return (
    <div className="chat-feed" ref={feedRef}>
      {events.length ? (
        <SessionTimeline events={events} sessionId={sessionId} attachments={attachments} />
      ) : (
        <p className="muted">{t('Сообщений пока нет.')}</p>
      )}
      <QuoteSelection container={feedRef} />
    </div>
  );
}

function eventIdentity(event: SessionEvent): string | null {
  for (const key of ['call_id', 'tool_call_id', 'id']) {
    if (typeof event.payload[key] === 'string') return event.payload[key] as string;
  }
  return null;
}

function SessionTimeline({
  events,
  sessionId,
  attachments,
}: {
  events: SessionEvent[];
  sessionId: string;
  attachments: Attachment[];
}): JSX.Element {
  const rows: JSX.Element[] = [];
  const consumed = new Set<number>();
  events.forEach((event, index) => {
    if (consumed.has(event.cursor)) return;
    if (event.kind === 'tool.call') {
      const identity = eventIdentity(event);
      const result = events
        .slice(index + 1)
        .find((candidate) => candidate.kind === 'tool.result' && (!identity || eventIdentity(candidate) === identity));
      if (result) consumed.add(result.cursor);
      rows.push(<ToolCard key={event.cursor} call={event} result={result} />);
      return;
    }
    if (event.kind === 'tool.result') {
      rows.push(<ToolCard key={event.cursor} result={event} />);
      return;
    }
    if (event.kind === 'diff') {
      rows.push(<DiffCard key={event.cursor} event={event} sessionId={sessionId} />);
      return;
    }
    if (event.kind === 'approval.request') {
      rows.push(<ApprovalCard key={event.cursor} event={event} />);
      return;
    }
    if (event.kind === 'session.status') {
      rows.push(<SessionStatusRow key={event.cursor} event={event} />);
      return;
    }
    if (event.kind === 'message') {
      const role = event.payload.role === 'user' ? 'user' : 'assistant';
      rows.push(
        <div className={`chat-message ${role === 'user' ? 'user' : ''}`} key={event.cursor}>
          <small>
            {role === 'user' ? t('Вы') : t('Ассистент')} · {new Date(event.ts).toLocaleTimeString()}
          </small>
          {role === 'user' ? (
            <>
              <p className="chat-message-text">{eventText(event)}</p>
              <AttachmentChips items={attachments} ids={event.payload.attachment_ids} />
            </>
          ) : (
            <div className="chat-message-text">
              <MarkdownView content={eventText(event)} />
              {isPartial(event) && <span className="typing-caret" aria-label={t('Агент пишет')} />}
            </div>
          )}
          {!isPartial(event) && (
            <div className="message-actions">
              <CopyButton text={eventText(event)} />
            </div>
          )}
        </div>,
      );
      return;
    }
    if (event.kind === 'output') {
      rows.push(
        <div className="chat-message" key={event.cursor}>
          <small>
            {t('Вывод ·')} {new Date(event.ts).toLocaleTimeString()}
          </small>
          <pre className="output-text">{eventText(event)}</pre>
        </div>,
      );
    }
  });
  return <>{rows}</>;
}

function ToolCard({ call, result }: { call?: SessionEvent; result?: SessionEvent }): JSX.Element {
  const name = String(
    call?.payload.name ?? call?.payload.tool ?? result?.payload.name ?? result?.payload.tool ?? t('команда'),
  );
  const exitCode = result?.payload.exit_code;
  return (
    <details className="tool-card">
      <summary>
        {t('Команда:')} {name}
        {result && exitCode !== undefined ? t(' · код выхода {0}', String(exitCode)) : ''}
      </summary>
      {call && <pre>{eventText(call)}</pre>}
      {result && <pre>{eventText(result)}</pre>}
    </details>
  );
}

function DiffCard({ event, sessionId }: { event: SessionEvent; sessionId: string }): JSX.Element {
  const changes = Array.isArray(event.payload.changes) ? event.payload.changes : [];
  const paths = changes
    .map((change) => (change && typeof change === 'object' && 'path' in change ? String(change.path) : ''))
    .filter(Boolean);
  const fallback = typeof event.payload.path === 'string' ? [event.payload.path] : [];
  return (
    <article className="diff-card">
      <strong>{t('Изменения файлов')}</strong>
      <ul>
        {[...new Set([...paths, ...fallback])].map((path) => (
          <li key={path}>
            <Link to={`/sessions/${sessionId}/files?path=${encodeURIComponent(path)}`}>{path}</Link>
          </li>
        ))}
      </ul>
    </article>
  );
}

function SessionStatusRow({ event }: { event: SessionEvent }): JSX.Element {
  return (
    <div className="session-status-row">
      <StatusBadge value={String(event.payload.status ?? 'unknown')} />
      <span>{String(event.payload.reason ?? t('Статус сессии обновлён'))}</span>
      <small>
        {t('источник:')} {event.source}
      </small>
    </div>
  );
}

function ApprovalCard({ event }: { event: SessionEvent }): JSX.Element {
  const [state, setState] = useState<'pending' | 'approved' | 'rejected'>('pending');
  const [error, setError] = useState('');
  const action = String(event.payload.action ?? t('Операция'));
  const summary = String(event.payload.summary ?? t('Требуется подтверждение действия агента.'));
  const risk = String(event.payload.risk ?? t('не указан'));
  const decide = async (decision: 'approved' | 'rejected') => {
    const id =
      typeof event.payload.approval_id === 'string'
        ? event.payload.approval_id
        : typeof event.payload.id === 'string'
          ? event.payload.id
          : '';
    if (!id) {
      setError(t('Идентификатор подтверждения отсутствует.'));
      return;
    }
    try {
      await api(`/approvals/${encodeURIComponent(id)}/decision`, {
        method: 'POST',
        body: JSON.stringify({ decision }),
      });
      setState(decision);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404)
        setError(t('API подтверждений пока недоступен. Карточка доступна только для чтения.'));
      else setError(cause instanceof Error ? cause.message : t('Решение не отправлено'));
    }
  };
  return (
    <article className="approval-card" aria-label={t('Запрос подтверждения')}>
      <div className="card-top">
        <strong>{t('Нужно подтверждение')}</strong>
        <StatusBadge value={state} />
      </div>
      <p>
        <b>{t('Действие:')}</b> {action}
      </p>
      <p>{summary}</p>
      <p className="muted">
        <b>{t('Риск:')}</b> {risk}
      </p>
      {error && <ErrorBanner message={error} />}
      {state === 'pending' && !error.includes('только для чтения') && (
        <div className="approval-actions">
          <button onClick={() => void decide('approved')}>{t('Разрешить')}</button>
          <button className="button-danger" onClick={() => void decide('rejected')}>
            {t('Отклонить')}
          </button>
        </div>
      )}
    </article>
  );
}

function SessionEvents({ sessionId }: { sessionId: string }): JSX.Element {
  const [filter, setFilter] = useState('');
  const all = useSessionEvents(sessionId, 300, 'events');
  // Streamed partials are only an in-progress copy of the final answer; they would bury everything else.
  const events = useMemo(
    () => all.filter((event) => !isPartial(event) && (!filter || event.kind === filter)).reverse(),
    [all, filter],
  );
  return (
    <div>
      <div className="panel-heading">
        <h2>{t('События')}</h2>
        <select aria-label={t('Фильтр событий')} value={filter} onChange={(event) => setFilter(event.target.value)}>
          <option value="">{t('все типы')}</option>
          {eventKinds.map((kind) => (
            <option key={kind}>{kind}</option>
          ))}
        </select>
      </div>
      {events.length ? (
        <ol className="event-log">
          {events.map((event) => (
            <li key={event.cursor}>
              <div className="event-meta">
                <StatusBadge value={event.kind} />
                <small>#{event.cursor}</small>
                <time>{new Date(event.ts).toLocaleTimeString()}</time>
              </div>
              <pre>{JSON.stringify(event.payload, null, 2)}</pre>
              {typeof event.payload.path === 'string' && (
                <Link
                  to={`/sessions/${sessionId}/files?path=${encodeURIComponent(event.payload.path)}${event.payload.line ? `#L${event.payload.line}` : ''}`}
                >
                  {t('Открыть файл')}
                </Link>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">{t('Событий пока нет.')}</p>
      )}
    </div>
  );
}

function SessionTree({ session }: { session: Session }): JSX.Element {
  return (
    <div className="session-tree">
      <h2>{t('Граф агента')}</h2>
      <div className="tree-node">
        <StatusBadge value={session.status} />
        <span>{session.title || session.id}</span>
      </div>
      {session.parent_session_id ? (
        <div className="tree-parent">
          {t('↳ родитель:')}{' '}
          <Link to={`/workspace?session=${session.parent_session_id}`}>{session.parent_session_id}</Link>
        </div>
      ) : (
        <p className="muted">{t('Родительская сессия не задана.')}</p>
      )}
    </div>
  );
}

function NewSessionDialog({
  projects,
  projectId,
  onClose,
  onCreated,
}: {
  projects: Project[];
  projectId: string;
  onClose: () => void;
  onCreated: (session: Session) => void;
}): JSX.Element {
  const workers = useApi<Worker[]>('/workers');
  const accounts = useApi<AccountProfile[]>('/accounts');
  const accountNotFound = accounts.error.includes('(404)');
  const [form, setForm] = useState({
    project_id: projectId,
    worker_id: '',
    account_profile_id: '',
    model: '',
    engine: 'codex',
    title: '',
    prompt: '',
    branch: '',
    mode: 'single',
    executor_count: '2',
    executor_account_profile_id: '',
    executor_model: 'gpt-5.6-luna',
  });
  const [attachments, setAttachments] = useState<File[]>([]);
  const [attachError, setAttachError] = useState('');
  // Picked or pasted files add up (same limits as the session composer); they upload when the session starts.
  const addAttachments = (list: File[]) => {
    setAttachError('');
    const tooBig = list.find((file) => file.size > 20 * 1024 * 1024);
    if (tooBig) return setAttachError(t('{0}: файл больше 20 МБ.', tooBig.name));
    setAttachments((current) => {
      if (current.length + list.length > 10) {
        setAttachError(t('Можно прикрепить не больше 10 файлов.'));
        return current;
      }
      return [...current, ...list];
    });
  };
  const [manualMerge, setManualMerge] = useState(false);
  const [error, setError] = useState('');
  const account = accounts.data?.find((item) => item.id === form.account_profile_id);
  const orchestratorAccounts = (accounts.data ?? []).filter((item) => item.kind === 'claude_code_subscription');
  const executorAccounts = (accounts.data ?? []).filter((item) => item.kind === 'codex_subscription');
  const selectedProject = projects.find((item) => item.id === form.project_id);
  const models = account?.models ?? [];
  const selectedWorker = useApi<WorkerDetails>(
    form.worker_id ? `/workers/${encodeURIComponent(form.worker_id)}` : null,
  );
  const availableEngines = Object.keys(selectedWorker.data?.capabilities ?? {}).filter((engine) =>
    engines.includes(engine as (typeof engines)[number]),
  );
  const info = useApi<{ demo: boolean }>('/system/info');
  const engineOptions = info.data?.demo ? MOCK_ENGINES : availableEngines.length ? availableEngines : [...engines];
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  // A subscription account runs only its own CLI: the engine list follows the chosen account.
  const allowedEngines = engineOptions.filter(
    (engine) =>
      !account ||
      (account.kind === 'claude_code_subscription'
        ? engine === 'claude_code'
        : account.kind === 'codex_subscription'
          ? engine === 'codex'
          : true),
  );
  useEffect(() => {
    // Keep the state equal to what the select shows: the default engine may not be offered here (a demo has
    // only mock engines), or the chosen account may not run it (a Claude account cannot run Codex).
    if (!allowedEngines.includes(form.engine)) update('engine', allowedEngines[0] ?? engineOptions[0] ?? 'codex');
  }, [allowedEngines.join(','), form.engine]);
  useEffect(() => {
    if (!form.worker_id && workers.data) {
      const online = workers.data.find((worker) => worker.status === 'online');
      if (online) update('worker_id', online.id);
    }
  }, [form.worker_id, workers.data]);
  useEffect(() => {
    if (!form.account_profile_id && accounts.data) {
      const matching = accounts.data.find((item) => item.worker_id === form.worker_id && item.status === 'connected');
      if (matching) update('account_profile_id', matching.id);
    }
  }, [accounts.data, form.account_profile_id, form.worker_id]);
  useEffect(() => {
    if (form.mode === 'orchestrated') {
      if (!orchestratorAccounts.some((item) => item.id === form.account_profile_id))
        update('account_profile_id', orchestratorAccounts[0]?.id ?? '');
      if (!executorAccounts.some((item) => item.id === form.executor_account_profile_id))
        update('executor_account_profile_id', executorAccounts[0]?.id ?? '');
    }
  }, [
    form.mode,
    form.account_profile_id,
    form.executor_account_profile_id,
    orchestratorAccounts.map((item) => item.id).join(','),
    executorAccounts.map((item) => item.id).join(','),
  ]);
  // With files the session is created on hold: upload them, post the prompt that refers to them, then queue
  // it — otherwise the worker could start before the upload ends and the agent would never see the files.
  const attachAndStart = async (session: Session, prompt: string) => {
    if (!attachments.length) return;
    const uploaded: Attachment[] = [];
    for (const file of attachments) {
      const data = new FormData();
      data.append('file', file);
      uploaded.push(await api<Attachment>(`/sessions/${session.id}/attachments`, { method: 'POST', body: data }));
    }
    await api(`/sessions/${session.id}/events`, {
      method: 'POST',
      body: JSON.stringify([
        { kind: 'message', payload: { role: 'user', text: prompt, attachment_ids: uploaded.map((item) => item.id) } },
      ]),
    });
    await api(`/sessions/${session.id}/start`, { method: 'POST' });
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const prompt = form.prompt.trim();
    if (!prompt) {
      setError(t('Введите задачу или промпт.'));
      return;
    }
    try {
      const title = form.title.trim() || prompt.split('\n')[0].slice(0, 120);
      if (form.mode === 'orchestrated') {
        const created = await api<{ session_id?: string; session?: Session } | Session>('/orchestrations', {
          method: 'POST',
          body: JSON.stringify({
            project_id: form.project_id,
            title,
            spec: prompt,
            orchestrator: { account_profile_id: form.account_profile_id },
            executors: {
              count: Number(form.executor_count),
              account_profile_id: form.executor_account_profile_id,
              model: form.executor_model || 'gpt-5.6-luna',
            },
            branch: form.branch || 'main',
            hold: attachments.length > 0,
            manual_merge: manualMerge,
          }),
        });
        // The API answers {session_id, task_id}; load the orchestrator session to open it.
        const session =
          'session_id' in created && created.session_id
            ? await api<Session>(`/sessions/${created.session_id}`)
            : 'session' in created && created.session
              ? created.session
              : (created as Session);
        await attachAndStart(session, prompt);
        onCreated(session);
        return;
      }
      const task = await api<Task>(`/projects/${encodeURIComponent(form.project_id)}/tasks`, {
        method: 'POST',
        body: JSON.stringify({ title, body: prompt, idempotency_key: crypto.randomUUID() }),
      });
      const created = await api<Session>('/sessions', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          task_id: task.id,
          worker_id: form.worker_id,
          account_profile_id: form.account_profile_id || null,
          model: form.model || account?.default_model || 'unknown',
          provider: account?.kind?.includes('anthropic') ? 'anthropic' : 'openai',
          auth_mode: account?.kind?.includes('subscription') ? 'subscription' : 'api_key',
          workdir: selectedProject?.allowed_paths?.[0] || '/',
          branch: form.branch || null,
          title,
          hold: attachments.length > 0,
        }),
      });
      await attachAndStart(created, prompt);
      onCreated(created);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t('Не удалось создать сессию'));
    }
  };
  return (
    <Dialog open title={t('Новая сессия')} onClose={onClose}>
      <form className="create-form" onSubmit={submit}>
        <div className="panel-heading">
          <span className="muted">{t('Запуск агента в выбранном проекте')}</span>
        </div>
        {error && <ErrorBanner message={error} />}
        <fieldset className="mode-switch" aria-label={t('Режим запуска')}>
          <legend>{t('Режим')}</legend>
          <label>
            <input
              type="radio"
              name="session-mode"
              checked={form.mode === 'single'}
              onChange={() => update('mode', 'single')}
            />{' '}
            {t('Один агент')}
          </label>
          <label>
            <input
              type="radio"
              name="session-mode"
              checked={form.mode === 'orchestrated'}
              onChange={() => update('mode', 'orchestrated')}
            />{' '}
            {t('Оркестратор + исполнители')}
          </label>
        </fieldset>
        <label>
          {t('Проект')}
          <select required value={form.project_id} onChange={(event) => update('project_id', event.target.value)}>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Worker
          <select value={form.worker_id} onChange={(event) => update('worker_id', event.target.value)}>
            {[
              ...(workers.data ?? [])
                .sort((a, b) => Number(b.status === 'online') - Number(a.status === 'online'))
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} · {item.status}
                  </option>
                )),
            ]}
          </select>
          {!workers.loading && !workers.data?.some((worker) => worker.status === 'online') && (
            <small className="field-error">{t('Нет online worker — сессия останется в очереди.')}</small>
          )}
        </label>
        {!accountNotFound && (
          <label>
            {form.mode === 'orchestrated' ? t('Оркестратор (Claude)') : t('Аккаунт')}
            <select
              value={form.account_profile_id}
              onChange={(event) => update('account_profile_id', event.target.value)}
            >
              <option value="">{t('без профиля')}</option>
              {(form.mode === 'orchestrated' ? orchestratorAccounts : (accounts.data ?? []))
                .filter((item) => !form.worker_id || item.worker_id === form.worker_id)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.status}
                  </option>
                ))}
            </select>
          </label>
        )}
        {form.mode === 'orchestrated' && (
          <>
            <label>
              {t('Исполнители (Codex)')}
              <select
                value={form.executor_account_profile_id}
                onChange={(event) => update('executor_account_profile_id', event.target.value)}
                required
              >
                {executorAccounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.status}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('Количество исполнителей')}
              <select value={form.executor_count} onChange={(event) => update('executor_count', event.target.value)}>
                {[1, 2, 3, 4].map((count) => (
                  <option key={count}>{count}</option>
                ))}
              </select>
            </label>
            <label>
              {t('Модель исполнителей')}
              <input value={form.executor_model} onChange={(event) => update('executor_model', event.target.value)} />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={manualMerge} onChange={(event) => setManualMerge(event.target.checked)} />
              {t('Принимать слияния вручную (оркестратор просит, вы нажимаете «Принять»)')}
            </label>
          </>
        )}
        <label>
          {t('Модель')}
          <input
            list="available-models"
            value={form.model}
            onChange={(event) => update('model', event.target.value)}
            placeholder={account?.default_model || t('Введите модель вручную')}
          />
          <datalist id="available-models">
            {models.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
        </label>
        {form.mode === 'single' && (
          <label>
            {t('Движок')}
            <select value={form.engine} onChange={(event) => update('engine', event.target.value)}>
              {allowedEngines.map((engine) => (
                <option key={engine}>{engine}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          {t('Задача/название')}
          <input value={form.title} onChange={(event) => update('title', event.target.value)} />
        </label>
        <label>
          {t('Задача / промпт')}
          <textarea
            required
            value={form.prompt}
            onChange={(event) => update('prompt', event.target.value)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              if (!event.dataTransfer.files.length) return;
              event.preventDefault();
              addAttachments(Array.from(event.dataTransfer.files));
            }}
            onPaste={(event) => {
              const pasted = Array.from(event.clipboardData.files);
              if (pasted.length) {
                event.preventDefault();
                addAttachments(pasted);
              }
            }}
            placeholder={t('Что должен сделать агент? Файлы можно вставить сюда (Ctrl+V)')}
          />
        </label>
        <div className="attachment-picker">
          <span className="attachment-picker-label">
            {form.mode === 'orchestrated' ? t('Прикрепить файлы к ТЗ') : t('Прикрепить файлы')}
          </span>
          <label className="button-secondary attachment-picker-button">
            <Icon name="attach" size={15} /> {t('Выбрать файлы')}
            <input
              type="file"
              multiple
              hidden
              onChange={(event) => {
                addAttachments(Array.from(event.target.files ?? []));
                event.currentTarget.value = '';
              }}
            />
          </label>
          {attachments.length > 0 && (
            <div className="attachment-chips" aria-label={t('Прикреплённые файлы')}>
              {attachments.map((file, index) => (
                <span key={`${file.name}-${index}`} className="attachment-chip">
                  <Icon name={file.type.startsWith('image/') ? 'image' : 'file'} size={15} /> {file.name}
                  <button
                    type="button"
                    aria-label={t('Удалить {0}', file.name)}
                    onClick={() => setAttachments((current) => current.filter((_, at) => at !== index))}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </span>
              ))}
            </div>
          )}
          {attachError && <small className="field-error">{attachError}</small>}
        </div>
        <label>
          {t('Ветка')}
          <input value={form.branch} onChange={(event) => update('branch', event.target.value)} placeholder="main" />
        </label>
        <button
          type="submit"
          disabled={
            !form.project_id ||
            (form.mode === 'orchestrated' && (!form.account_profile_id || !form.executor_account_profile_id))
          }
        >
          {t('Запустить')}
        </button>
      </form>
    </Dialog>
  );
}

const PLAN_ICON: Record<PlanStep['status'], string> = {
  pending: 'draft',
  in_progress: 'running',
  done: 'completed',
  blocked: 'failed',
};
const PLAN_LABEL: Record<PlanStep['status'], string> = {
  pending: t('ждёт'),
  in_progress: t('в работе'),
  done: t('готово'),
  blocked: t('заблокировано'),
};
const MERGE_LABEL: Record<string, string> = {
  requested: t('ждёт вашего решения о слиянии'),
  merging: t('сливается…'),
  merged: t('влито'),
  conflict: t('конфликт при слиянии'),
  rejected: t('слияние отклонено'),
};

const tokens = (value: number) =>
  value >= 1_000_000 ? `${(value / 1_000_000).toFixed(1)}M` : `${Math.round(value / 1000)}k`;

function UsageLine({ usage, account }: { usage: Usage; account: AccountUsage }): JSX.Element {
  const window5h = account?.windows.find((item) => item.kind === 'five_hour');
  return (
    <small className="usage-line">
      {tokens(usage.input_tokens)} {t('вход (')}
      {tokens(usage.cached_input_tokens)} {t('из кэша) ·')} {tokens(usage.output_tokens)} {t('выход')}
      {usage.cost_usd !== null && ` · ≈ $${usage.cost_usd.toFixed(2)}`}
      {account && ` · ${account.name}`}
      {window5h && t(' · лимит 5 ч: {0}%', Math.round(window5h.used_percent))}
    </small>
  );
}

function ExecutorPanel({ session }: { session: Session }): JSX.Element {
  const view = useApi<OrchestrationView>(`/sessions/${encodeURIComponent(session.id)}/orchestration`, {
    refreshMs: 10_000,
  });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const executors = view.data?.executors ?? [];
  const working = executors.filter((item) => ['queued', 'starting', 'running'].includes(item.status)).length;
  const decide = async (id: string, action: 'accept' | 'reject') => {
    setBusy(id);
    setError('');
    try {
      const reason = action === 'reject' ? (window.prompt(t('Почему отклоняете? (уйдёт оркестратору)')) ?? '') : '';
      await api(`/sessions/${encodeURIComponent(id)}/merge/${action}`, {
        method: 'POST',
        body: action === 'reject' ? JSON.stringify({ reason }) : undefined,
      });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t('Не получилось'));
    } finally {
      setBusy('');
    }
  };
  return (
    <section className="executor-panel" aria-label={t('Исполнители')}>
      {error && <ErrorBanner message={error} />}
      <div className="panel-heading">
        <h2>{t('План')}</h2>
        {view.data?.plan_updated_at && (
          <small className="muted">
            {t('обновлён')} {ago(view.data.plan_updated_at)}
          </small>
        )}
      </div>
      {view.data?.plan.length ? (
        <ol className="plan-list">
          {view.data.plan.map((step, index) => (
            <li key={index}>
              <StatusIcon value={PLAN_ICON[step.status]} label={PLAN_LABEL[step.status]} />
              <span>{step.title}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">{t('Оркестратор ещё не опубликовал план.')}</p>
      )}
      <div className="panel-heading">
        <h2>{t('Исполнители')}</h2>
        <strong>
          {working} {t('из')} {view.data?.max_executors ?? '—'} {t('работают')}
          {view.data?.manual_merge ? t(' · слияние вручную') : ''}
        </strong>
      </div>
      {view.data && <UsageLine usage={view.data.orchestrator.usage} account={view.data.orchestrator.account} />}
      {view.error && (
        <p className="muted">
          {t('Сводка оркестрации недоступна:')} {view.error}
        </p>
      )}
      {executors.map((executor) => (
        <article className="executor-card" key={executor.id}>
          <div className="panel-heading">
            <strong>{executor.title}</strong>
            <StatusBadge value={executor.status} />
          </div>
          <small>
            {executor.branch || t('ветка не назначена')} · {executor.changed_files?.length ?? 0} {t('файлов')}
          </small>
          <UsageLine usage={executor.usage} account={executor.account} />
          {executor.last_message && <p>{executor.last_message}</p>}
          {executor.merge && (
            <div className={`merge-box merge-${executor.merge.state}`}>
              <strong>{MERGE_LABEL[executor.merge.state] ?? executor.merge.state}</strong>
              {executor.merge.summary && <p>{executor.merge.summary}</p>}
              {executor.merge.error && <p className="muted">{executor.merge.error}</p>}
              {['requested', 'conflict'].includes(executor.merge.state) && (
                <span className="merge-actions">
                  <Link className="button-secondary" to={`/sessions/${session.id}/files`}>
                    {t('Посмотреть diff')}
                  </Link>
                  <button
                    className="button-secondary"
                    disabled={busy === executor.id}
                    onClick={() => void decide(executor.id, 'reject')}
                  >
                    {t('Отклонить')}
                  </button>
                  <button disabled={busy === executor.id} onClick={() => void decide(executor.id, 'accept')}>
                    {t('Принять слияние')}
                  </button>
                </span>
              )}
            </div>
          )}
          <Link to={`/sessions/${executor.id}`}>{t('Открыть')}</Link>
        </article>
      ))}
      {!view.loading && !executors.length && !view.error && (
        <p className="muted">{t('Исполнители появятся после запуска.')}</p>
      )}
    </section>
  );
}
