import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  type Edge,
  type Node,
  type NodeChange,
  Position,
  type XYPosition,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEventStream } from '../api/events';
import type { AgentGraph as AgentGraphData, GraphNode } from '../api/types';
import { ago, useApi } from '../api/useApi';
import { api, ApiError } from '../api/client';
import type { SessionEvent } from '../api/types';
import { ConfirmDialog, ErrorBanner, Loading, StatusBadge } from './ui';
import { t } from '../i18n';

const FOLD = 'fold:';
const ROW = 104;
const COLUMN = 320;
const inactive = new Set(['completed', 'failed', 'offline']);

function readPositions(key: string): Record<string, XYPosition> {
  try {
    return JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, XYPosition>;
  } catch {
    return {};
  }
}

type Props = { projectId: string; compact?: boolean; onSelect?: (node: GraphNode) => void };

function label(node: GraphNode): string {
  return node.title || node.id.slice(0, 8);
}

export function AgentGraph({ projectId, compact = false, onSelect }: Props): JSX.Element {
  const graph = useApi<AgentGraphData>(projectId ? `/graph?project_id=${encodeURIComponent(projectId)}` : null);
  const events = useEventStream({ limit: 100 });
  const [selected, setSelected] = useState<GraphNode | null>(null);

  // Reload only when a new status change arrives, not on every streamed token.
  const lastStatusCursor = useMemo(
    () =>
      events.reduce((max, event) => (event.kind === 'session.status' && event.cursor > max ? event.cursor : max), 0),
    [events],
  );
  useEffect(() => {
    if (lastStatusCursor) graph.reload();
  }, [lastStatusCursor, graph.reload]);

  // Finished sub-agents fold into one "N inactive" node per parent so big orchestrations stay readable.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const layout = useMemo(() => {
    const items = graph.data?.nodes ?? [];
    const allEdges = graph.data?.edges ?? [];
    const parents = new Map<string, string>();
    allEdges.forEach((edge) => parents.set(edge.to, edge.from));
    const hidden = new Map<string, number>();
    const visible = items.filter((item) => {
      const parent = parents.get(item.id);
      if (!parent || !inactive.has(item.status ?? '') || expanded.has(parent)) return true;
      hidden.set(parent, (hidden.get(parent) ?? 0) + 1);
      return false;
    });
    const folds = [...hidden.entries()].map(([parent, count]) => ({ id: `${FOLD}${parent}`, parent, count }));
    const unfold = [...expanded].filter((parent) =>
      items.some((item) => parents.get(item.id) === parent && inactive.has(item.status ?? '')),
    );
    // Tree layout: a parent's children (and its fold node) sit in one contiguous block to its right,
    // the parent is centred on them, so edges never cross between different parents.
    const card = (item: GraphNode): Node => ({
      id: item.id,
      type: 'default',
      className: 'agent-node',
      position: { x: 0, y: 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: { label: <GraphNodeCard node={item} /> },
    });
    const foldNode = (id: string, text: string): Node => ({
      id,
      type: 'default',
      className: 'agent-node agent-node-fold',
      position: { x: 0, y: 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: { label: <span className="agent-fold-label">{text}</span> },
    });
    const byId = new Map<string, Node>(visible.map((item) => [item.id, card(item)]));
    folds.forEach((fold) => byId.set(fold.id, foldNode(fold.id, t('▸ {0} неактивных', fold.count))));
    unfold.forEach((parent) => byId.set(`${FOLD}${parent}`, foldNode(`${FOLD}${parent}`, t('▾ свернуть неактивные'))));
    const children = new Map<string, string[]>();
    const addChild = (parent: string, child: string) => children.set(parent, [...(children.get(parent) ?? []), child]);
    visible.forEach((item) => {
      const parent = parents.get(item.id);
      if (parent && byId.has(parent)) addChild(parent, item.id);
    });
    [...folds.map((fold) => fold.parent), ...unfold].forEach((parent) => addChild(parent, `${FOLD}${parent}`));
    let row = 0;
    const placeTree = (id: string, depth: number): number => {
      const kids = children.get(id) ?? [];
      const ys = kids.map((kid) => placeTree(kid, depth + 1));
      const y = ys.length ? (ys[0] + ys[ys.length - 1]) / 2 : row++ * ROW;
      byId.get(id)!.position = { x: depth * COLUMN, y };
      return y;
    };
    visible
      .filter((item) => !parents.get(item.id) || !byId.has(parents.get(item.id)!))
      .forEach((item) => {
        placeTree(item.id, 0);
        row += 0.4; // a little air between separate trees
      });
    const flowNodes = [...byId.values()];
    const ids = new Set(flowNodes.map((node) => node.id));
    const flowEdges: Edge[] = [
      ...allEdges.map((edge) => ({ source: edge.from, target: edge.to })),
      ...[...folds.map((fold) => fold.parent), ...unfold].map((parent) => ({
        source: parent,
        target: `${FOLD}${parent}`,
      })),
    ]
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, ...edge, animated: false }));
    return { nodes: flowNodes, edges: flowEdges };
  }, [graph.data, expanded]);
  // Blocks the owner dragged keep their place (per project, in this browser).
  const storageKey = `aihub.graph-positions.${projectId}`;
  const [moved, setMoved] = useState<Record<string, XYPosition>>(() => readPositions(storageKey));
  useEffect(() => setMoved(readPositions(storageKey)), [storageKey]);
  const nodes = useMemo(
    () => layout.nodes.map((node) => (moved[node.id] ? { ...node, position: moved[node.id] } : node)),
    [layout.nodes, moved],
  );
  const { edges } = layout;
  const onNodesChange = (changes: NodeChange[]) => {
    const next = { ...moved };
    let changed = false;
    changes.forEach((change) => {
      if (change.type === 'position' && change.position) {
        next[change.id] = change.position;
        changed = true;
      }
    });
    if (!changed) return;
    setMoved(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // storage is optional
    }
  };
  const resetLayout = () => {
    setMoved({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // storage is optional
    }
  };

  if (!projectId) return <p className="muted">{t('Выберите проект, чтобы увидеть граф.')}</p>;
  if (graph.loading && !graph.data) return <Loading />;
  if (graph.error) return <ErrorBanner message={graph.error} />;
  if (!graph.data?.nodes.length) return <p className="muted">{t('В проекте нет сессий или задач.')}</p>;

  const select = (node: Node) => {
    if (node.id.startsWith(FOLD)) {
      const parent = node.id.slice(FOLD.length);
      setExpanded((current) => {
        const next = new Set(current);
        if (next.has(parent)) next.delete(parent);
        else next.add(parent);
        return next;
      });
      return;
    }
    const item = graph.data?.nodes.find((candidate) => candidate.id === node.id) ?? null;
    setSelected(item);
    if (item) onSelect?.(item);
  };
  return (
    <div className={compact ? 'agent-graph compact' : 'agent-graph'}>
      {compact ? (
        <ul className="agent-list">
          {(graph.data?.nodes ?? []).map((node) => (
            <li key={node.id}>
              <button className="agent-list-item" onClick={() => select({ id: node.id } as Node)}>
                <span>
                  <strong>{label(node)}</strong>
                  <small>
                    {node.engine ?? node.type} · {node.model ?? '—'}
                  </small>
                </span>
                <StatusBadge value={node.status ?? 'unknown'} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="agent-flow" aria-label={t('Граф агентов')}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            colorMode={colorMode()}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
            nodesDraggable
            onNodesChange={onNodesChange}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => select(node)}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} />
            {Object.keys(moved).length > 0 && (
              <Panel position="top-right">
                <button className="button-secondary" onClick={resetLayout}>
                  {t('Сбросить раскладку')}
                </button>
              </Panel>
            )}
          </ReactFlow>
        </div>
      )}
      {selected && <AgentDetails node={selected} projectId={projectId} />}
    </div>
  );
}

function colorMode(): 'dark' | 'light' {
  const forced = document.documentElement.dataset.theme;
  if (forced === 'dark' || forced === 'light') return forced;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function GraphNodeCard({ node }: { node: GraphNode }): JSX.Element {
  return (
    <div className="graph-node-card">
      <div className="graph-node-top">
        <strong title={node.id}>{node.title || `${node.engine ?? node.type} · ${node.id.slice(0, 8)}`}</strong>
        <StatusBadge value={node.status ?? 'unknown'} />
      </div>
      <small>
        {node.engine ?? node.type}
        {node.model ? ` · ${node.model}` : ''}
      </small>
    </div>
  );
}

function AgentDetails({ node, projectId }: { node: GraphNode; projectId: string }): JSX.Element {
  const isSession = node.type === 'session';
  const events = useApi<SessionEvent[]>(
    isSession ? `/events?session_id=${encodeURIComponent(node.id)}&limit=10` : null,
  );
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<'stop' | 'retry' | ''>('');
  const [error, setError] = useState('');
  const action = async (name: 'stop' | 'retry') => {
    setPendingAction(name);
  };
  const confirmAction = async () => {
    const name = pendingAction;
    setPendingAction('');
    if (!name) return;
    setBusy(true);
    setError('');
    try {
      await api(`/sessions/${node.id}/${name}`, { method: 'POST' });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t('Операция не выполнена'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside className="agent-details panel">
      <div className="panel-heading">
        <h2>{t('Подробности')}</h2>
        <StatusBadge value={node.status ?? 'unknown'} />
      </div>
      <dl className="details-list">
        <dt>{t('Заголовок')}</dt>
        <dd>{label(node)}</dd>
        <dt>{t('Двигатель / модель')}</dt>
        <dd>
          {node.engine ?? '—'} / {node.model ?? '—'}
        </dd>
        <dt>{t('Аккаунт')}</dt>
        <dd>{node.account_profile_id ?? '—'}</dd>
        <dt>Worker</dt>
        <dd>{node.worker_id ?? '—'}</dd>
        <dt>{t('Задача')}</dt>
        <dd>{node.task_id ?? '—'}</dd>
        <dt>{t('Длительность')}</dt>
        <dd>{node.duration_s == null ? '—' : t('{0} с', Math.round(node.duration_s))}</dd>
        <dt>{t('Последнее событие')}</dt>
        <dd>
          {node.latest_event?.kind ?? '—'} {node.latest_event?.ts ? `(${ago(node.latest_event.ts)})` : ''}
        </dd>
      </dl>
      {isSession && (
        <>
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
          {error && <ErrorBanner message={error} />}
          <div className="card-actions">
            <Link
              className="button-secondary"
              to={`/workspace?project=${encodeURIComponent(projectId)}&session=${encodeURIComponent(node.id)}`}
            >
              {t('Открыть сессию')}
            </Link>
            <button
              className="button-secondary"
              onClick={() => void action('stop')}
              disabled={busy || node.status === 'completed' || node.status === 'failed'}
            >
              {t('Остановить')}
            </button>
            <button
              className="button-secondary"
              onClick={() => void action('retry')}
              disabled={busy || (node.status !== 'completed' && node.status !== 'failed')}
            >
              {t('Повторить')}
            </button>
          </div>
          <h3>{t('Последние события')}</h3>
          {events.error ? (
            <ErrorBanner message={events.error} />
          ) : (
            <ul className="mini-event-list">
              {(events.data ?? [])
                .slice(-5)
                .reverse()
                .map((event) => (
                  <li key={event.cursor}>
                    <StatusBadge value={event.kind} /> <span>{new Date(event.ts).toLocaleTimeString()}</span>
                  </li>
                ))}
            </ul>
          )}
        </>
      )}
    </aside>
  );
}
