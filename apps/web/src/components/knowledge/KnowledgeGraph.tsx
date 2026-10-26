import { useEffect, useRef, useState } from 'react';
import type cytoscape from 'cytoscape';
import type { NodeSingular } from 'cytoscape';
import type { KnowledgeGraphResponse } from '../../api/types';
import { createGraphEngine } from './graph/engine';
import { labelLayer } from './graph/labels';
import type { GraphContainer, GraphController, GraphDepth, GraphMode } from './graph/types';
import { t } from '../../i18n';

type Props = {
  graph: KnowledgeGraphResponse;
  selectedId: string | null;
  mode: GraphMode;
  depth: GraphDepth;
  selectedEdgesOnly: boolean;
  fitRequest: number;
  resetRequest: number;
  onSelect: (id: string | null) => void;
  onOpen: (id: string) => void;
};
// One saved layout per set of notes: a changed vault gets a fresh layout for the new notes only.
const positionsKey = (graph: KnowledgeGraphResponse) =>
  `aihub.kg.positions.v1:${graph.nodes
    .map((node) => node.id)
    .sort()
    .join('|')}`;

export default function KnowledgeGraph({
  graph,
  selectedId,
  mode,
  depth,
  selectedEdgesOnly,
  fitRequest,
  resetRequest,
  onSelect,
  onOpen,
}: Props): JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const controller = useRef<GraphController | null>(null);
  // Latest callbacks without recreating the engine (parents may pass new functions every render).
  const handlers = useRef({ onSelect, onOpen });
  handlers.current = { onSelect, onOpen };
  const [hover, setHover] = useState<{ label: string; x: number; y: number } | null>(null);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 600px)').matches);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 600px)');
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (!container.current || isMobile) return undefined;
    // The engine owns layout, resize and persistence; this shell only wires props and the tooltip.
    const created = createGraphEngine(
      container.current as GraphContainer,
      graph,
      {
        storageKey: positionsKey(graph),
        mode,
        depth,
        selectedEdgesOnly,
        onSelect: (id) => handlers.current.onSelect(id),
        onOpen: (id) => handlers.current.onOpen(id),
      },
      labelLayer,
    );
    controller.current = created;
    const over = (event: cytoscape.EventObject) => {
      const node = event.target as NodeSingular;
      const position = node.renderedPosition();
      setHover({ label: node.data('fullLabel'), x: position.x + 12, y: position.y + 12 });
    };
    created.cy.on('mouseover', 'node', over);
    created.cy.on('mouseout', 'node', () => setHover(null));
    return () => {
      created.destroy();
      controller.current = null;
      setHover(null);
    };
    // Only new data or the mobile switch recreate the engine: re-running the layout on clicks is forbidden.
  }, [graph, isMobile]);
  // Separate effects: a click (selection) must not re-run setMode, which re-fits the camera.
  useEffect(() => {
    controller.current?.setMode(mode);
  }, [mode]);
  useEffect(() => {
    controller.current?.setDepth(depth);
  }, [depth]);
  useEffect(() => {
    controller.current?.setSelectedEdgesOnly(selectedEdgesOnly);
  }, [selectedEdgesOnly]);
  useEffect(() => {
    controller.current?.select(selectedId);
  }, [selectedId]);
  useEffect(() => {
    if (fitRequest) controller.current?.fit();
  }, [fitRequest]);
  useEffect(() => {
    if (resetRequest) controller.current?.resetLayout();
  }, [resetRequest]);
  if (isMobile)
    return (
      <div className="knowledge-graph-mobile-list" aria-label={t('Список заметок графа')}>
        <p className="muted">{t('На телефоне граф заменён списком заметок.')}</p>
        <ul>
          {graph.nodes.map((node) => (
            <li key={node.id}>
              <button className={selectedId === node.id ? 'selected' : ''} onClick={() => onSelect(node.id)}>
                <strong>{node.title}</strong>
                <small>
                  {node.project_id ?? node.path ?? t('Общее')} · {node.degree} {t('связей')}
                </small>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  return (
    <div className="knowledge-graph-stage">
      <div ref={container} className="knowledge-graph-canvas" role="img" aria-label={t('Граф связей базы знаний')} />
      {hover && (
        <div className="knowledge-graph-tooltip" style={{ left: hover.x, top: hover.y }}>
          {hover.label}
        </div>
      )}
    </div>
  );
}
