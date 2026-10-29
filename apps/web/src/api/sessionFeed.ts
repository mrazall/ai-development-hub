import { createContext, useContext, useMemo } from 'react';
import { useEventStream } from './events';
import type { SessionEvent } from './types';
import { arrayOrEmpty, useApi } from './useApi';

/**
 * Session history plus live events, de-duplicated by cursor and in order.
 * `view` asks the server to drop engine bookkeeping for that tab (chat, the agent terminal, the events
 * log), so a long run still shows its recent history. The live stream starts after the loaded history.
 */
/**
 * A session and its continuations are one conversation: session id → the ids of its thread, oldest first.
 * The workspace provides it; the feeds (chat, agent terminal, events) show the whole thread.
 */
export const SessionThreads = createContext<Map<string, string[]>>(new Map());

export function useSessionEvents(
  sessionId: string,
  limit = 300,
  view?: 'chat' | 'activity' | 'events',
): SessionEvent[] {
  const threads = useContext(SessionThreads);
  const ids = threads.get(sessionId) ?? [sessionId];
  const key = ids.join(',');
  const history = useApi<SessionEvent[]>(
    `/events?${ids.length > 1 ? `session_ids=${encodeURIComponent(key)}` : `session_id=${encodeURIComponent(sessionId)}`}&limit=${limit}&newest=true${view ? `&view=${view}` : ''}`,
  );
  const member = useMemo(() => new Set(key.split(',')), [key]);
  const historyEvents = arrayOrEmpty(history.data);
  const loaded = history.data !== null && historyEvents.every((event) => member.has(event.session_id));
  const after = loaded ? Math.max(0, ...historyEvents.map((event) => event.cursor)) : undefined;
  // New events come only from the newest session of the thread.
  const live = useEventStream({ sessionId, limit, enabled: after !== undefined, after });
  return useMemo(() => {
    const byCursor = new Map<number, SessionEvent>();
    [...historyEvents, ...live].forEach((event) => byCursor.set(event.cursor, event));
    // While switching sessions the loader still holds the previous session's history for a moment;
    // cursors are global, so those foreign events would be taken as "already shown" for this one.
    return [...byCursor.values()].filter((event) => member.has(event.session_id)).sort((a, b) => a.cursor - b.cursor);
  }, [history.data, historyEvents, live, member]);
}

export function isUserMessage(event: SessionEvent): boolean {
  return event.kind === 'message' && event.payload.role === 'user';
}

/** Assistant prose: a streamed partial, or the final text of a Claude/Codex message. */
export function assistantText(event: SessionEvent): string | null {
  if (event.kind !== 'message' || event.payload.role === 'user') return null;
  const text = event.payload.text;
  if (typeof text !== 'string' || !text.trim()) return null;
  const raw = event.payload.raw_type;
  // `result` repeats the final answer; other raw types without prose are engine bookkeeping.
  if (raw && raw !== 'assistant' && raw !== 'item.completed') return null;
  return text;
}

export function isPartial(event: SessionEvent): boolean {
  return event.payload.partial === true;
}

/** Engine bookkeeping (init, usage, result echo…) that belongs in the events panel, not the chat. */
export function isTechnical(event: SessionEvent): boolean {
  if (event.kind === 'message') return !isUserMessage(event) && assistantText(event) === null;
  if (event.kind === 'output') return Boolean(event.payload.raw_type);
  return false;
}

/**
 * Chat view of a session: technical events dropped, and of the streamed partials only the latest one
 * of a still-unfinished answer kept, so a reply grows in place instead of repeating per word.
 */
export function chatEvents(events: SessionEvent[]): SessionEvent[] {
  const kept: SessionEvent[] = [];
  let finalSeen = false;
  let partialKept = false;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (isUserMessage(event)) {
      finalSeen = false;
      partialKept = false;
    } else if (assistantText(event) !== null) {
      if (isPartial(event)) {
        if (finalSeen || partialKept) continue;
        partialKept = true;
      } else {
        finalSeen = true;
      }
    } else if (isTechnical(event)) {
      continue;
    }
    kept.push(event);
  }
  return kept.reverse();
}
