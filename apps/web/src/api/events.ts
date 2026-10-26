import { useEffect, useState } from 'react';
import { api, changedEvent } from './client';

export const eventKinds = [
  'session.status',
  'tool.call',
  'tool.result',
  'message',
  'output',
  'approval.request',
  'approval.decision',
  'diff',
  'test.result',
  'checkpoint',
  'handoff',
  'heartbeat',
  'plan',
] as const;

export const notificationEventKind = 'notification';

export type StreamEvent = {
  cursor: number;
  session_id: string;
  kind: string;
  source: string;
  ts: string;
  payload: Record<string, unknown>;
  redacted: boolean;
};

export function useEventStream(
  options: { sessionId?: string; limit?: number; enabled?: boolean; after?: number } = {},
): StreamEvent[] {
  const limit = options.limit ?? 20;
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const enabled = options.enabled ?? true;
  useEffect(() => {
    setEvents([]);
    if (!enabled) return undefined;
    let source: EventSource | undefined;
    let stopped = false;
    // Start where the loaded history ends: from 0 the stream replayed a long session event by event.
    // Without an explicit start: from now on (-1); every caller loads its history through the REST API.
    let cursor = options.after ?? -1;
    // Bursts (a reconnect, a busy agent) land in one render per frame instead of one per event.
    let pending: StreamEvent[] = [];
    let frame = 0;
    const flush = () => {
      frame = 0;
      const batch = pending;
      pending = [];
      setEvents((current) => [...current, ...batch].slice(-limit));
      // A status change makes every list on screen (sessions, tasks, project icons) refetch at once.
      if (batch.some((event) => event.kind === 'session.status' || event.kind === 'plan'))
        window.dispatchEvent(new Event(changedEvent));
    };
    const connect = async () => {
      const { ticket } = await api<{ ticket: string }>('/events/stream-ticket', { method: 'POST' });
      if (stopped) return;
      const params = new URLSearchParams({ ticket, after: String(cursor) });
      if (options.sessionId) params.set('session_id', options.sessionId);
      source = new EventSource(`/api/v0/events/stream?${params.toString()}`);
      const handle = (message: MessageEvent<string>) => {
        const event = JSON.parse(message.data) as StreamEvent;
        cursor = Math.max(cursor, event.cursor);
        pending.push(event);
        if (!frame) frame = window.requestAnimationFrame(flush);
      };
      [...eventKinds, notificationEventKind].forEach((kind) => source?.addEventListener(kind, handle));
      source.onerror = () => {
        source?.close();
        if (!stopped) window.setTimeout(() => void connect(), 500);
      };
    };
    void connect();
    return () => {
      stopped = true;
      window.cancelAnimationFrame(frame);
      source?.close();
    };
  }, [options.sessionId, limit, enabled, options.after]);
  return events;
}
