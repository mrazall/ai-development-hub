import { useMemo } from 'react';
import { useEventStream } from './events';
import type { SessionEvent } from './types';
import { useApi } from './useApi';

/**
 * Session history plus live events, de-duplicated by cursor and in order.
 * `view` asks the server to drop engine bookkeeping for that tab (chat, the agent terminal, the events
 * log), so a long run still shows its recent history. The live stream starts after the loaded history.
 */
export function useSessionEvents(
  sessionId: string,
  limit = 300,
  view?: 'chat' | 'activity' | 'events',
): SessionEvent[] {
  const history = useApi<SessionEvent[]>(
    `/events?session_id=${encodeURIComponent(sessionId)}&limit=${limit}&newest=true${view ? `&view=${view}` : ''}`,
  );
  const loaded = history.data !== null && history.data.every((event) => event.session_id === sessionId);
  const after = loaded ? Math.max(0, ...(history.data ?? []).map((event) => event.cursor)) : undefined;
  const live = useEventStream({ sessionId, limit, enabled: after !== undefined, after });
  return useMemo(() => {
    const byCursor = new Map<number, SessionEvent>();
    [...(history.data ?? []), ...live].forEach((event) => byCursor.set(event.cursor, event));
    // While switching sessions the loader still holds the previous session's history for a moment;
    // cursors are global, so those foreign events would be taken as "already shown" for this one.
    return [...byCursor.values()].filter((event) => event.session_id === sessionId).sort((a, b) => a.cursor - b.cursor);
  }, [history.data, live, sessionId]);
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
