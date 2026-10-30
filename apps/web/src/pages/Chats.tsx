import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useEventStream, type StreamEvent } from '../api/events';
import type { AccountProfile, Chat, ChatMessage } from '../api/types';
import { useApi } from '../api/useApi';
import { ErrorBanner, Loading } from '../components/ui';
import { MarkdownView } from '../components/MarkdownView';
import { LogoMark } from '../components/Logo';
import { CopyButton, QuoteSelection, quoteEvent } from '../components/copy';
import { Icon } from '../components/ui/icons';
import { t } from '../i18n';
import { CLAUDE_MODELS } from '../api/models';
import { Thinking } from '../components/time';
import { stepDescription, ToolGroup, toolLabel } from '../components/ToolGroup';
import { TimeAgo } from '../components/time';

// Claude Code --effort levels; empty = the worker default (low, to save subscription limits).
const EFFORTS: [string, string][] = [
  ['', t('Усилие: по умолчанию')],
  ['low', t('Усилие: низкое')],
  ['medium', t('Усилие: среднее')],
  ['high', t('Усилие: высокое')],
  ['xhigh', t('Усилие: очень высокое')],
  ['max', t('Усилие: максимум')],
];

type SendOptions = { model?: string; effort?: string; account?: string };
const optionsBody = ({ model, effort, account }: SendOptions) => ({
  ...(model ? { model } : {}),
  ...(effort ? { effort } : {}),
  ...(account ? { account_profile_id: account } : {}),
});

const examples = [
  t('Что у меня на VDS?'),
  t('Найди в памяти, как настроен бэкап'),
  t('Помоги с командой для проверки диска'),
  t('Что изменилось в проекте за сегодня?'),
];

function chatList(data: Chat[] | { chats?: Chat[] } | null): Chat[] {
  return Array.isArray(data) ? data : (data?.chats ?? []);
}

function dayGroup(value: string): string {
  const age = (Date.now() - new Date(value).getTime()) / 86_400_000;
  if (age < 1 && new Date(value).getDate() === new Date().getDate()) return t('Сегодня');
  if (age < 2) return t('Вчера');
  if (age < 7) return t('Неделя');
  return t('Раньше');
}

export function Chats(): JSX.Element {
  const { id } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [, setRefresh] = useState(0);
  const list = useApi<Chat[] | { chats?: Chat[] }>(`/chats${query ? `?q=${encodeURIComponent(query)}` : ''}`);
  const chatId = id && id !== 'new' ? id : undefined;
  const selected = useApi<Chat>(chatId ? `/chats/${encodeURIComponent(chatId)}` : null);
  const chats = useMemo(() => chatList(list.data), [list.data]);

  const [createError, setCreateError] = useState('');
  const create = async (text: string, options: SendOptions) => {
    setCreateError('');
    try {
      const chat = await api<Chat>('/chats', {
        method: 'POST',
        body: JSON.stringify({ text, ...optionsBody(options) }),
      });
      setRefresh((value) => value + 1);
      navigate(`/chats/${chat.id}`);
    } catch (cause) {
      setCreateError(cause instanceof ApiError ? cause.message : t('Не удалось создать чат'));
    }
  };

  return (
    <div className={`chats-shell ${id ? 'has-selection' : ''}`}>
      <aside className="chats-sidebar" aria-label={t('Список чатов')}>
        <div className="chats-sidebar-heading">
          <div>
            <p className="eyebrow">{t('РАБОЧЕЕ ПРОСТРАНСТВО')}</p>
            <h1>{t('Чаты')}</h1>
          </div>
          <button className="chat-new-button" onClick={() => navigate('/chats/new')} aria-label={t('Новый чат')}>
            <Icon name="plus" />
          </button>
        </div>
        <button className="chat-new-wide" onClick={() => navigate('/chats/new')}>
          <Icon name="plus" size={16} />
          {t('Новый чат')}
        </button>
        <label className="chat-search">
          <Icon name="search" size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('Поиск чатов…')}
            aria-label={t('Поиск чатов')}
          />
        </label>
        {list.error && <ErrorBanner message={list.error} />}
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <ChatList
            chats={chats}
            selected={chatId}
            onSelect={(chatId) => navigate(`/chats/${chatId}`)}
            onRefresh={() => {
              list.reload();
              setRefresh((value) => value + 1);
            }}
          />
        )}
      </aside>
      <main className="chat-conversation">
        {chatId ? (
          <Conversation
            chat={selected.data}
            loading={selected.loading}
            error={selected.error}
            onRefresh={() => {
              selected.reload();
              setRefresh((value) => value + 1);
            }}
          />
        ) : (
          <NewChat onPick={(text, options) => void create(text, options)} error={createError} />
        )}
      </main>
    </div>
  );
}

function ChatList({
  chats,
  selected,
  onSelect,
  onRefresh,
}: {
  chats: Chat[];
  selected?: string;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}): JSX.Element {
  const sorted = [...chats].sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) || new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
  const groups = [t('Сегодня'), t('Вчера'), t('Неделя'), t('Раньше')];
  return (
    <div className="chat-list">
      {groups.map((group) => {
        const items = sorted.filter((chat) => dayGroup(chat.updated_at) === group);
        if (!items.length) return null;
        return (
          <section key={group}>
            <h2>{group}</h2>
            {items.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                active={chat.id === selected}
                onClick={() => onSelect(chat.id)}
                onRefresh={onRefresh}
              />
            ))}
          </section>
        );
      })}
      {!sorted.length && <p className="muted chat-list-empty">{t('Чатов пока нет.')}</p>}
    </div>
  );
}

function ChatRow({
  chat,
  active,
  onClick,
  onRefresh,
}: {
  chat: Chat;
  active: boolean;
  onClick: () => void;
  onRefresh: () => void;
}): JSX.Element {
  const [menu, setMenu] = useState(false);
  const rename = async () => {
    const title = window.prompt(t('Название чата'), chat.title);
    if (title?.trim()) {
      await api(`/chats/${chat.id}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) });
      onRefresh();
    }
  };
  const archive = async () => {
    if (window.confirm(t('Архивировать этот чат?'))) {
      await api(`/chats/${chat.id}`, { method: 'DELETE' });
      onRefresh();
    }
  };
  const pin = async () => {
    await api(`/chats/${chat.id}`, { method: 'PATCH', body: JSON.stringify({ pinned: !chat.pinned }) });
    onRefresh();
  };
  return (
    <div className={`chat-row ${active ? 'active' : ''}`}>
      <button className="chat-row-main" onClick={onClick}>
        <span className="chat-row-title">
          {chat.pinned && (
            <span aria-label={t('Закреплён')} title={t('Закреплён')}>
              ★{' '}
            </span>
          )}
          {chat.title || t('Новый чат')}
        </span>
        <small>
          <TimeAgo value={chat.updated_at} />
        </small>
      </button>
      <button
        className="chat-row-menu"
        aria-label={t('Действия: {0}', chat.title)}
        onClick={() => setMenu((value) => !value)}
      >
        <Icon name="more" />
      </button>
      {menu && (
        <div className="chat-row-actions">
          <button onClick={() => void pin()}>{chat.pinned ? t('Открепить') : t('Закрепить')}</button>
          <button onClick={() => void rename()}>{t('Переименовать')}</button>
          <button onClick={() => void archive()}>{t('Архивировать')}</button>
        </div>
      )}
    </div>
  );
}

function NewChat({
  onPick,
  error = '',
}: {
  onPick: (text: string, options: SendOptions) => void;
  error?: string;
}): JSX.Element {
  const [draft, setDraft] = useState('');
  return (
    <div className="chat-empty">
      <LogoMark size={48} className="chat-empty-logo" />
      <h1>{t('О чём поговорим?')}</h1>
      <p className="muted">{t('Быстрые ответы с доступом к памяти и инструментам вашего проекта.')}</p>
      <div className="chat-examples">
        {examples.map((example) => (
          <button key={example} className="chat-example" onClick={() => setDraft(example)}>
            {example}
            <Icon name="open" size={15} />
          </button>
        ))}
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <Composer value={draft} onChange={setDraft} onSend={onPick} chooseAccount />
    </div>
  );
}

function Conversation({
  chat,
  loading,
  error,
  onRefresh,
}: {
  chat: Chat | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}): JSX.Element {
  const [sending, setSending] = useState(false);
  const [composerError, setComposerError] = useState('');
  const [draft, setDraft] = useState('');
  // Only the chat's current session, and only once it is known (no id would stream every session).
  const live = useEventStream({
    sessionId: chat?.session_id ?? undefined,
    limit: 200,
    enabled: Boolean(chat?.session_id),
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const [nearBottom, setNearBottom] = useState(true);
  const messages = useMemo(
    () => mergeMessages(chat?.messages ?? [], live, chat?.session_id ?? ''),
    [chat?.messages, live, chat?.session_id],
  );
  const finished = live.some(
    (event) =>
      event.session_id === chat?.session_id &&
      event.kind === 'session.status' &&
      ['completed', 'failed'].includes(String(event.payload.status ?? '')),
  );
  useEffect(() => {
    // Reload stored history when the turn ends: partial text is replaced by the final answer.
    if (finished) onRefresh();
  }, [finished]);
  useEffect(() => {
    // «Ответить» on a selected phrase: put it as a quote at the top of the draft.
    const onQuote = (event: Event) => {
      setDraft((current) => `${(event as CustomEvent<string>).detail}${current}`);
      window.setTimeout(() => document.querySelector<HTMLTextAreaElement>('.chat-composer-new textarea')?.focus());
    };
    window.addEventListener(quoteEvent, onQuote);
    return () => window.removeEventListener(quoteEvent, onQuote);
  }, []);
  useEffect(() => {
    if (nearBottom) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, nearBottom]);
  if (loading && !chat) return <Loading />;
  if (error) return <ErrorBanner message={error} />;
  if (!chat) return <NewChat onPick={(text) => setDraft(text)} />;
  const running = ['queued', 'starting', 'running'].includes(chat.status ?? '') && !finished;
  const send = async (text: string, options: SendOptions = {}) => {
    if (!text.trim() || !chat.session_id) return;
    setSending(true);
    setComposerError('');
    try {
      // The account stays: the conversation lives in that account's Claude home.
      await api(`/sessions/${chat.session_id}/continue`, {
        method: 'POST',
        body: JSON.stringify({ text: text.trim(), ...optionsBody({ ...options, account: undefined }) }),
      });
      setDraft('');
      onRefresh();
    } catch (cause) {
      setComposerError(cause instanceof ApiError ? cause.message : t('Сообщение не отправлено'));
    } finally {
      setSending(false);
    }
  };
  const stop = async () => {
    if (chat.session_id) await api(`/sessions/${chat.session_id}/stop`, { method: 'POST' }).catch(() => undefined);
  };
  const retry = () => {
    const last = [...messages].reverse().find((message) => message.role === 'user');
    if (last) void send(last.text);
  };
  return (
    <div className="conversation-layout">
      <header className="conversation-header">
        <Link className="chat-back" to="/chats" aria-label={t('Все чаты')}>
          <Icon name="back" />
        </Link>
        <div>
          <h1>{chat.title || t('Новый чат')}</h1>
          <small className="muted">
            {chat.model || t('Модель профиля')} · {chat.account_profile_id ?? t('аккаунт по умолчанию')}
            {chat.status === 'running' ? t(' · думает…') : ''}
          </small>
        </div>
        <div className="conversation-actions">
          <span className="context-meter" title={t('Использовано контекста')}>
            <span
              style={{ width: `${Math.min(100, ((chat.context?.used ?? 0) / (chat.context?.limit || 1)) * 100)}%` }}
            />
            {chat.context
              ? `${Math.round(chat.context.used / 1000)}k / ${Math.round(chat.context.limit / 1000)}k`
              : t('Контекст')}
          </span>
          <button className="button-secondary" onClick={retry}>
            {t('Повторить')}
          </button>
        </div>
      </header>
      <div
        className="message-scroll"
        ref={scrollRef}
        onScroll={(event) => {
          const node = event.currentTarget;
          setNearBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 80);
        }}
      >
        {groupTools(messages).map((item, index, items) =>
          Array.isArray(item) ? (
            <ToolGroup
              key={item[0].id ?? `tools-${index}`}
              running={(sending || running) && index === items.length - 1}
              endedAt={(items[index + 1] as ChatMessage | undefined)?.created_at}
              steps={item.map((step, at) => ({
                key: step.id ?? at,
                label: step.tool_summary || toolLabel(step.tool_name),
                at: step.created_at,
                detail: step.text ? <pre>{step.text}</pre> : undefined,
              }))}
            />
          ) : (
            <Message key={item.id ?? `${item.role}-${index}`} message={item} />
          ),
        )}
        <QuoteSelection container={scrollRef} />
        {(sending || running) && messages.at(-1)?.role !== 'tool' && (
          <Thinking label={turnLabel(messages)} since={turnStart(messages)} />
        )}
        {!nearBottom && (
          <button
            className="jump-latest"
            onClick={() => {
              scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
              setNearBottom(true);
            }}
          >
            {t('↓ К последнему')}
          </button>
        )}
      </div>
      <div className="conversation-composer">
        {composerError && (
          <p className="field-error" role="alert">
            {composerError}
          </p>
        )}
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={(text, options) => void send(text, options)}
          busy={sending || running}
          defaultModel={chat.model ?? ''}
          defaultEffort={chat.effort ?? ''}
          account={chat.account_profile_id ?? ''}
          onStop={() => void stop()}
        />
      </div>
    </div>
  );
}

// The current turn for the «working» line: since the last question; what the agent is doing now.
function turnStart(messages: ChatMessage[]): string | undefined {
  return [...messages].reverse().find((message) => message.role === 'user')?.created_at;
}
function turnLabel(messages: ChatMessage[]): string {
  const last = messages[messages.length - 1];
  if (last?.role === 'tool') return t('работает');
  if (last?.role === 'assistant' && last.partial) return t('пишет');
  return t('думает');
}

function mergeMessages(messages: ChatMessage[], events: StreamEvent[], sessionId: string): ChatMessage[] {
  const result = [...messages];
  // Stored history already holds everything up to its last cursor; only newer live events are appended.
  const lastCursor = Math.max(0, ...messages.map((message) => Number(message.id) || 0));
  for (const event of events) {
    if (event.session_id !== sessionId || event.cursor <= lastCursor) continue;
    const payload = event.payload;
    const text = typeof payload.text === 'string' ? payload.text : '';
    if (event.kind === 'message' && text.trim() && payload.raw_type !== 'result') {
      const role = payload.role === 'user' ? 'user' : 'assistant';
      const last = result.at(-1);
      if (last?.partial && last.role === role)
        result[result.length - 1] = { ...last, text, partial: Boolean(payload.partial) };
      else
        result.push({
          id: `event-${event.cursor}`,
          role,
          text,
          partial: Boolean(payload.partial),
          created_at: event.ts,
        });
    } else if (event.kind === 'tool.call') {
      result.push({
        id: `tool-${event.cursor}`,
        role: 'tool',
        tool_name: typeof payload.name === 'string' ? payload.name : t('Инструмент'),
        tool_summary: stepDescription(payload.command),
        text: typeof payload.summary === 'string' ? payload.summary : '',
        created_at: event.ts,
      });
    }
  }
  return result;
}

/** Consecutive tool calls become one group (a list); other messages stay as they are. */
function groupTools(messages: ChatMessage[]): (ChatMessage | ChatMessage[])[] {
  const items: (ChatMessage | ChatMessage[])[] = [];
  for (const message of messages) {
    const last = items.at(-1);
    if (message.role === 'tool' && Array.isArray(last)) last.push(message);
    else items.push(message.role === 'tool' ? [message] : message);
  }
  return items;
}

function Message({ message }: { message: ChatMessage }): JSX.Element {
  return (
    <article className={`chat-message ${message.role}`}>
      <div className="message-author">
        {message.role === 'user' ? t('Вы') : 'Claude'}
        {message.partial && <span className="partial-dot"> {t('· печатает')}</span>}
      </div>
      {message.role === 'assistant' ? <MarkdownView content={message.text} /> : <p>{message.text}</p>}
      {!message.partial && (
        <div className="message-actions">
          <CopyButton text={message.text} />
        </div>
      )}
    </article>
  );
}

function Composer({
  value = '',
  onChange,
  onSend,
  busy = false,
  onStop,
  defaultModel = '',
  defaultEffort = '',
  account = '',
  chooseAccount = false,
}: {
  value?: string;
  onChange?: (value: string) => void;
  onSend: (value: string, options: SendOptions) => void;
  busy?: boolean;
  onStop?: () => void;
  defaultModel?: string;
  defaultEffort?: string;
  /** The chat's account (shown, fixed: a conversation cannot move to another account). */
  account?: string;
  /** A new chat: the account can be chosen. */
  chooseAccount?: boolean;
}): JSX.Element {
  const [internal, setInternal] = useState(value);
  const text = onChange ? value : internal;
  const setText = onChange ?? setInternal;
  const area = useRef<HTMLTextAreaElement>(null);
  const accounts = useApi<AccountProfile[]>('/accounts');
  const claudeAccounts = useMemo(
    () => (accounts.data ?? []).filter((item) => item.kind === 'claude_code_subscription'),
    [accounts.data],
  );
  const [model, setModel] = useState(defaultModel);
  const [effort, setEffort] = useState(defaultEffort);
  const [chosenAccount, setChosenAccount] = useState('');
  useEffect(() => setModel(defaultModel), [defaultModel]);
  useEffect(() => setEffort(defaultEffort), [defaultEffort]);
  const models = useMemo(() => {
    const fromProfiles = claudeAccounts.flatMap((item) => [item.default_model, ...(item.models ?? [])]);
    return [...new Set([...CLAUDE_MODELS.map(([value]) => value), ...fromProfiles].filter(Boolean) as string[])];
  }, [claudeAccounts]);
  useEffect(() => {
    if (area.current) {
      area.current.style.height = 'auto';
      area.current.style.height = `${Math.min(area.current.scrollHeight, 180)}px`;
    }
  }, [text]);
  const submit = () => {
    if (text.trim()) onSend(text, { model, effort, account: chooseAccount ? chosenAccount : undefined });
  };
  const accountLabel = (item: AccountProfile) => `${item.name}${item.status === 'ready' ? '' : ` (${item.status})`}`;
  return (
    <form
      className="chat-composer-new"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={area}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder={t('Написать сообщение…')}
        aria-label={t('Сообщение')}
        rows={1}
      />
      <div className="composer-footer">
        <div className="composer-options">
          {chooseAccount ? (
            <select
              value={chosenAccount}
              onChange={(event) => setChosenAccount(event.target.value)}
              aria-label={t('Аккаунт')}
              title={t('Аккаунт Claude, с которого идёт чат')}
            >
              <option value="">{t('Аккаунт: автоматически')}</option>
              {claudeAccounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {t('Аккаунт:')} {accountLabel(item)}
                </option>
              ))}
            </select>
          ) : (
            <span className="composer-account" title={t('Чат продолжается на том же аккаунте')}>
              {t('Аккаунт:')}{' '}
              {claudeAccounts.find((item) => item.id === account)?.name ?? (account || t('по умолчанию'))}
            </span>
          )}
          <select value={model} onChange={(event) => setModel(event.target.value)} aria-label={t('Модель')}>
            <option value="">{t('Модель профиля')}</option>
            {models.map((item) => (
              <option key={item} value={item}>
                {CLAUDE_MODELS.find(([value]) => value === item)?.[1] ?? item}
              </option>
            ))}
          </select>
          <select value={effort} onChange={(event) => setEffort(event.target.value)} aria-label={t('Усилие')}>
            {EFFORTS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {busy ? (
          <button type="button" className="button-secondary" onClick={onStop}>
            {t('Стоп')}
          </button>
        ) : (
          <button type="submit" disabled={!text.trim()}>
            {t('Отправить')}
          </button>
        )}
      </div>
    </form>
  );
}
