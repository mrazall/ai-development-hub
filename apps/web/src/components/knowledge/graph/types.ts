// Knowledge graph contract shared by the engine (engine.ts), the label layer (labels.ts),
// the UI shell (KnowledgeGraph.tsx) and the browser checks (e2e). Change all sides together.
import type { Core } from 'cytoscape';
import type { KnowledgeGraphResponse } from '../../../api/types';

/** overview — all notes, faint edges, few labels; projects — grouped by project/folder; focus — selection and neighbours only. */
export type GraphMode = 'overview' | 'projects' | 'focus';

export type GraphDepth = 1 | 2;

export type GraphEngineOptions = {
  /** Key for persisted node positions (localStorage); one per dataset, e.g. 'aihub.kg.positions.v1:<hash>'. */
  storageKey: string;
  mode: GraphMode;
  depth: GraphDepth;
  /** Show only the edges of the selected node (others hidden, not just faint). */
  selectedEdgesOnly: boolean;
  onSelect: (id: string | null) => void;
  /** Double click on a node: open the note. */
  onOpen: (id: string) => void;
};

export type GraphController = {
  cy: Core;
  setMode: (mode: GraphMode) => void;
  setDepth: (depth: GraphDepth) => void;
  setSelectedEdgesOnly: (value: boolean) => void;
  /** Select (and centre without re-layout) a node; null clears the selection. */
  select: (id: string | null) => void;
  /** Fit all visible elements with padding. */
  fit: () => void;
  /** Forget saved positions and run the deterministic layout again, then fit. */
  resetLayout: () => void;
  /** Replace the data (e.g. filters changed); keeps saved positions of nodes that remain. */
  update: (data: KnowledgeGraphResponse) => void;
  destroy: () => void;
};

/**
 * Label layer: decides which labels are visible so none overlap.
 * Called by the engine after layout, zoom, pan, selection and resize (debounced ~60 ms).
 * Priority: selected > its neighbours > hovered > high-degree nodes; at low zoom only the top few.
 * Implementations set the node data field `label` ('' hides it) and never move nodes.
 */
export type LabelLayer = {
  apply: (cy: Core, state: { selectedId: string | null; hoveredId: string | null }) => void;
};

/** The container element of a ready graph exposes its controller for browser checks. */
export type GraphContainer = HTMLDivElement & { __kg?: GraphController };

/** Visual tokens (Monochrome Signal); read from CSS variables at runtime, these are the fallbacks. */
export const GRAPH_COLORS = {
  background: '#141414',
  node: '#575757',
  nodeStrong: '#858580',
  ghost: '#3c3c3c',
  label: '#f0f0ed',
  edge: '#3c3c3c',
  accent: '#e6b85b',
} as const;
