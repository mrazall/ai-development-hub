import { type ReactNode, useEffect, useRef, useState } from 'react';
import { type ITheme, Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { api } from '../api/client';
import { copyText } from './copy';
import { useSessionAttachmentList } from './attachments';
import { assistantText, isPartial, isTechnical, isUserMessage, useSessionEvents } from '../api/sessionFeed';
import type { SessionEvent } from '../api/types';
import { t } from '../i18n';

type Status = { kind: 'connecting' } | { kind: 'connected' } | { kind: 'closed'; reason: string };

type ServerFrame = { t: 'ready' } | { t: 'o'; d: string } | { t: 'x'; reason: string };

// Reasons after which reconnecting is pointless.
const fatalReasons = new Set(['forbidden', 'not_found']);

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

// Visible on the dark canvas: the accent at low opacity (the --bg-active token barely differs from it).
const SELECTION = 'rgba(230, 184, 91, 0.35)';

/** Copy like a desktop terminal: Ctrl+C with a selection (else it stays SIGINT), Ctrl+Shift+C, right click. */
function enableCopy(term: Terminal, container: HTMLElement): () => void {
  term.attachCustomKeyEventHandler((event) => {
    if (event.type !== 'keydown' || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'c') return true;
    if (!term.hasSelection()) return !event.shiftKey;
    event.preventDefault();
    void copyText(term.getSelection());
    term.clearSelection();
    return false;
  });
  const onContextMenu = (event: MouseEvent) => {
    if (!term.hasSelection()) return;
    event.preventDefault();
    void copyText(term.getSelection());
    term.clearSelection();
  };
  container.addEventListener('contextmenu', onContextMenu);
  return () => container.removeEventListener('contextmenu', onContextMenu);
}

function ShellTerminal({ terminalId, initialInput }: { terminalId: string; initialInput?: string }): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>({ kind: 'connecting' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const term = new Terminal({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: 13,
      cursorBlink: true,
      scrollback: 5000,
      theme: terminalTheme('accent'),
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    const disableCopy = enableCopy(term, container);
    const unfollow = followTheme(term, 'accent');

    let socket: WebSocket | undefined;
    let stopped = false;
    let retryTimer: number | undefined;
    let resizeTimer: number | undefined;
    let delay = 1000;
    let lastSize = '';

    const send = (frame: object) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(frame));
    };
    const sendSize = () => {
      try {
        fit.fit();
      } catch {
        return;
      }
      const size = `${term.cols}x${term.rows}`;
      if (size === lastSize) return;
      lastSize = size;
      send({ t: 'z', c: term.cols, r: term.rows });
    };
    const scheduleReconnect = () => {
      if (stopped) return;
      retryTimer = window.setTimeout(() => void connect(), delay);
      delay = Math.min(delay * 2, 15000);
    };

    const connect = async () => {
      if (stopped) return;
      setStatus({ kind: 'connecting' });
      let ticket: string;
      try {
        ({ ticket } = await api<{ ticket: string }>('/events/stream-ticket', { method: 'POST' }));
      } catch (cause) {
        setStatus({ kind: 'closed', reason: cause instanceof Error ? cause.message : t('нет билета') });
        scheduleReconnect();
        return;
      }
      if (stopped) return;
      // The ticket goes in the first frame, never in the URL (access logs record query strings).
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${scheme}://${location.host}/api/v0/terminal/${encodeURIComponent(terminalId)}/ws`);
      socket = ws;
      let fatal = false;
      ws.onopen = () => {
        ws.send(JSON.stringify({ t: 'auth', ticket }));
      };
      ws.onmessage = (message) => {
        let frame: ServerFrame;
        try {
          frame = JSON.parse(String(message.data)) as ServerFrame;
        } catch {
          return;
        }
        if (frame.t === 'ready') {
          delay = 1000;
          lastSize = '';
          setStatus({ kind: 'connected' });
          sendSize();
          if (initialInput) send({ t: 'i', d: `${initialInput}\n` });
        } else if (frame.t === 'o') {
          term.write(frame.d);
        } else if (frame.t === 'x') {
          fatal = fatalReasons.has(frame.reason);
          setStatus({ kind: 'closed', reason: frame.reason });
        }
      };
      ws.onclose = () => {
        if (socket !== ws || stopped) return;
        setStatus((current) =>
          current.kind === 'closed' ? current : { kind: 'closed', reason: t('соединение потеряно') },
        );
        if (!fatal) scheduleReconnect();
      };
    };

    const dataSub = term.onData((data) => send({ t: 'i', d: data }));
    const observer = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(sendSize, 100);
    });
    observer.observe(container);
    void connect();

    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearTimeout(resizeTimer);
      observer.disconnect();
      dataSub.dispose();
      disableCopy();
      unfollow();
      socket?.close();
      term.dispose();
    };
  }, [terminalId, attempt, initialInput]);

  const label =
    status.kind === 'connecting'
      ? t('Подключение…')
      : status.kind === 'connected'
        ? t('Подключено')
        : t('Отключено: {0}', status.reason);
  return (
    <section className="session-terminal" aria-label={t('Терминал')}>
      <div className="session-terminal-header">
        <div>
          <h3>{t('Терминал')}</h3>
          <p className="muted">
            {t(
              'Shell в рабочей папке сессии на компьютере с worker-ом · копировать: выделить и Ctrl+C или правый клик',
            )}
          </p>
        </div>
        <div className="session-terminal-actions">
          <span className={`terminal-status terminal-status-${status.kind}`} role="status">
            {label}
          </span>
          <button className="button-secondary" onClick={() => setAttempt((value) => value + 1)}>
            {t('Переподключить')}
          </button>
        </div>
      </div>
      <div className="session-terminal-screen" ref={containerRef} />
    </section>
  );
}

/** Admin-only worker relay used by account login. The server resolves the relay id to a worker. */
export function WorkerTerminal({ workerId, command }: { workerId: string; command?: string }): JSX.Element {
  return <ShellTerminal terminalId={workerId} initialInput={command} />;
}

// Agent prose is bright white (ANSI 97) and commands are dim: fine on dark, unreadable on a light canvas.
// The light theme gets its own ANSI palette with dark ink; both follow theme switches live.
const LIGHT_ANSI = {
  black: '#1f1f1e',
  red: '#b42318',
  green: '#2f7a32',
  yellow: '#8a5a00',
  blue: '#1d4ed8',
  magenta: '#7e3aa8',
  cyan: '#0e6d80',
  white: '#5c5c58',
  brightBlack: '#6b6b67',
  brightRed: '#b42318',
  brightGreen: '#2f7a32',
  brightYellow: '#8a5a00',
  brightBlue: '#1d4ed8',
  brightMagenta: '#7e3aa8',
  brightCyan: '#0e6d80',
  brightWhite: '#141414',
};

function terminalTheme(cursor: 'accent' | 'hidden' = 'accent'): ITheme {
  const light = document.documentElement.dataset.theme === 'light';
  const background = cssVar('--bg-canvas', light ? '#f4f4f2' : 'black');
  return {
    background,
    foreground: cssVar('--text-primary', light ? '#1f1f1e' : 'white'),
    cursor: cursor === 'hidden' ? background : cssVar('--accent', 'goldenrod'),
    selectionBackground: SELECTION,
    ...(light ? LIGHT_ANSI : {}),
  };
}

/** Re-theme the terminal whenever the site theme changes. */
function followTheme(term: Terminal, cursor: 'accent' | 'hidden'): () => void {
  const observer = new MutationObserver(() => {
    term.options.theme = terminalTheme(cursor);
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => observer.disconnect();
}
const ansi = {
  dim: '\x1b[2m',
  bold: '\x1b[1m',
  cyan: '\x1b[36m',
  yellow: '\x1b[33m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  magenta: '\x1b[35m',
  prose: '\x1b[1;97m',
  reset: '\x1b[0m',
};
const crlf = (text: string) => text.replace(/\r?\n/g, '\r\n');
const MAX_COMMAND = 160;
const FAILED_TAIL_LINES = 5;
const TAIL_LINES = 3;

function commandOf(event: SessionEvent): string {
  const payload = event.payload;
  for (const key of ['command', 'cmd']) if (typeof payload[key] === 'string') return payload[key] as string;
  const input = payload.input;
  if (input && typeof input === 'object') {
    const fields = input as Record<string, unknown>;
    const value = fields.command ?? fields.file_path;
    if (typeof value === 'string') return `${String(payload.name ?? '')} ${value}`.trim();
  }
  return String(payload.name ?? payload.tool ?? t('инструмент'));
}

function resultOf(event: SessionEvent): string {
  const value = event.payload.output ?? event.payload.text ?? event.payload.content;
  if (typeof value === 'string') return value;
  return value === undefined ? '' : JSON.stringify(value);
}

/** Read-only, terminal-style live view of what the agent does: prose as it streams, commands, edits. */
function AgentView({ sessionId }: { sessionId: string }): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const state = useRef({ last: 0, streamed: '', batch: 0 });
  const events = useSessionEvents(sessionId, 300, 'activity');
  const attachments = useSessionAttachmentList(sessionId);
  const attachmentNames = useRef(new Map<string, string>());
  attachmentNames.current = new Map(attachments.items.map((item) => [item.id, item.original_name]));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const term = new Terminal({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: 13,
      scrollback: 10000,
      disableStdin: true,
      theme: terminalTheme('hidden'),
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    const disableCopy = enableCopy(term, container);
    const unfollow = followTheme(term, 'hidden');
    const observer = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {
        // the container is hidden (other tab or mobile layout)
      }
    });
    observer.observe(container);
    termRef.current = term;
    state.current = { last: 0, streamed: '', batch: 0 };
    return () => {
      observer.disconnect();
      disableCopy();
      unfollow();
      term.dispose();
      termRef.current = null;
    };
  }, [sessionId]);

  useEffect(() => {
    const term = termRef.current;
    // Written lines cannot be changed: wait for the attachment names before printing the history.
    if (!term || !attachments.loaded) return;
    const current = state.current;
    const endStream = () => {
      if (current.streamed) term.write('\r\n');
      current.streamed = '';
    };
    for (const event of events) {
      if (event.cursor <= current.last) continue;
      current.last = event.cursor;
      const text = assistantText(event);
      if (text !== null) {
        // Partials carry the whole answer so far: write only what is new, so it grows in place.
        // The agent's prose is bright white so it stands out from the dim command lines.
        if (current.streamed && text.startsWith(current.streamed)) {
          term.write(`${ansi.prose}${crlf(text.slice(current.streamed.length))}${ansi.reset}`);
        } else if (text !== current.streamed) {
          endStream();
          term.write(`\r\n${ansi.prose}${crlf(text)}${ansi.reset}`);
        }
        current.streamed = text;
        if (!isPartial(event)) endStream();
        continue;
      }
      if (isTechnical(event)) continue;
      endStream();
      if (isUserMessage(event)) {
        term.write(`\r\n${ansi.cyan}${ansi.bold}› ${crlf(String(event.payload.text ?? ''))}${ansi.reset}\r\n`);
        // Files sent with the message: names when known, a count otherwise.
        const ids = Array.isArray(event.payload.attachment_ids) ? event.payload.attachment_ids.map(String) : [];
        if (ids.length) {
          const names = ids.map((id) => attachmentNames.current.get(id)).filter(Boolean);
          const label = names.length === ids.length ? names.join(', ') : t('{0} файл(а)', ids.length);
          term.write(t('{0}  ⎘ вложения: {1}{2}\r\n', ansi.cyan, label, ansi.reset));
        }
      } else if (event.kind === 'tool.call') {
        // Commands stay folded to one dim line; their full output is in the Chat and Events tabs.
        const [first, ...rest] = commandOf(event).split(/\r?\n/);
        const line = `${first}${rest.length ? ' …' : ''}`;
        term.write(
          `${ansi.dim}▸ ${line.length > MAX_COMMAND ? `${line.slice(0, MAX_COMMAND)}…` : line}${ansi.reset}\r\n`,
        );
      } else if (event.kind === 'tool.result') {
        const code = event.payload.exit_code;
        const failed = (typeof code === 'number' && code !== 0) || event.payload.is_error === true;
        if (failed) {
          // Only a failure is worth unfolding: its last lines usually say why.
          const lines = resultOf(event).trimEnd().split(/\r?\n/).slice(-FAILED_TAIL_LINES);
          const label = typeof code === 'number' ? t('код выхода {0}', code) : t('ошибка');
          term.write(`${ansi.red}  ✗ ${label}${ansi.reset}\r\n`);
          if (lines.join('').trim())
            term.write(`${ansi.dim}${lines.map((line) => `  ${line}`).join('\r\n')}${ansi.reset}\r\n`);
        }
      } else if (event.kind === 'diff') {
        const changes = Array.isArray(event.payload.changes) ? event.payload.changes : [];
        const paths = changes
          .map((change) =>
            change && typeof change === 'object' ? String((change as { path?: unknown }).path ?? '') : '',
          )
          .filter(Boolean);
        if (typeof event.payload.path === 'string') paths.push(event.payload.path);
        new Set(paths).forEach((path) => term.write(`${ansi.green}✎ ${path}${ansi.reset}\r\n`));
      } else if (event.kind === 'session.status') {
        const reason = event.payload.reason ? ` — ${String(event.payload.reason)}` : '';
        term.write(`${ansi.magenta}● ${String(event.payload.status)}${reason}${ansi.reset}\r\n`);
      } else if (event.kind === 'output' && typeof event.payload.text === 'string') {
        term.write(`${ansi.dim}${crlf(event.payload.text)}${ansi.reset}\r\n`);
      }
    }
    // Keep a few blank lines under the last output so it can be scrolled above the bottom edge:
    // write them, then move the cursor back to where the next output continues.
    // Writes are parsed asynchronously, so read the cursor once they are done, and only for the latest batch.
    const batch = ++current.batch;
    term.write('', () => {
      if (batch !== current.batch || termRef.current !== term) return;
      const column = term.buffer.active.cursorX + 1;
      term.write(`${'\r\n'.repeat(TAIL_LINES)}\x1b[${TAIL_LINES}A\x1b[${column}G`);
    });
  }, [events, attachments.loaded]);

  return <div className="session-terminal-screen" ref={containerRef} />;
}

export type ExtraTab = { id: string; label: string; content: ReactNode };

/** Agent and Shell views of a session, plus any extra tabs the page adds (events, executors…). */
export function SessionTerminal({
  sessionId,
  extraTabs = [],
}: {
  sessionId: string;
  extraTabs?: ExtraTab[];
}): JSX.Element {
  const [tab, setTab] = useState('agent');
  const tabs = [{ id: 'agent', label: t('Агент') }, { id: 'shell', label: 'Shell' }, ...extraTabs];
  const extra = extraTabs.find((item) => item.id === tab);
  return (
    <div className="session-terminal-tabs">
      <div className="segmented" role="tablist" aria-label={t('Вид сессии')}>
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? 'active' : ''}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === 'shell' ? (
        <ShellTerminal terminalId={sessionId} />
      ) : extra ? (
        <section className="session-terminal session-terminal-extra" aria-label={extra.label}>
          {extra.content}
        </section>
      ) : (
        <section className="session-terminal" aria-label={t('Вывод агента')}>
          <div className="session-terminal-header">
            <div>
              <h3>{t('Агент')}</h3>
              <p className="muted">
                {t('Что агент пишет и делает — в реальном времени · копировать: выделить и Ctrl+C')}
              </p>
            </div>
          </div>
          <AgentView sessionId={sessionId} />
        </section>
      )}
    </div>
  );
}
