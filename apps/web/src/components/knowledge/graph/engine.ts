import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from 'cytoscape';
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import type { KnowledgeGraphResponse, KnowledgeGraphNode } from '../../../api/types';
import {
  GRAPH_COLORS,
  type GraphContainer,
  type GraphController,
  type GraphEngineOptions,
  type LabelLayer,
} from './types';
import { LABEL_FONT_FAMILY } from './labels';

// The layout and the feel follow Obsidian's graph view (its sim.js / renderer, v1.14): a d3-force
// simulation with the same forces, small nodes sized by links, labels at a constant screen size,
// hover highlighting the neighbourhood, and dragging that pulls the neighbours along.
const OBSIDIAN = {
  centerStrength: 0.1,
  linkDistance: 250,
  repel: -1000,
  repelDistanceMin: 30,
  collideRadius: 60,
  collideStrength: 0.5,
  velocityDecay: 0.4, // Obsidian: v *= 0.6 per tick
  dragAlphaTarget: 0.3,
};
const SETTLE_TICKS = 300;
const LABEL_SPACE = 24;
const FIT_PADDING = 48;
const LABEL_PX = 12;

type SavedPosition = { x: number; y: number };
type SavedPositions = Record<string, SavedPosition>;
type SimNode = SimulationNodeDatum & { id: string; group: string };
type SimLink = SimulationLinkDatum<SimNode>;

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function cssColor(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value && CSS.supports('color', value) ? value : fallback;
}

function hash(value: string): number {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}

function groupName(node: KnowledgeGraphNode): string {
  if (node.project_id) return `project:${node.project_id}`;
  const folder = node.path?.split('/').slice(0, -1).join('/');
  return folder ? `folder:${folder}` : 'folder:Общее';
}

function readPositions(key: string): SavedPositions {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        ([, value]) =>
          !!value &&
          typeof value === 'object' &&
          Number.isFinite((value as SavedPosition).x) &&
          Number.isFinite((value as SavedPosition).y),
      ),
    ) as SavedPositions;
  } catch {
    return {};
  }
}

function writePositions(key: string, cy: Core): void {
  const positions: SavedPositions = {};
  cy.nodes()
    .not('[?isGroup]')
    .forEach((node) => {
      positions[node.id()] = { ...node.position() };
    });
  try {
    localStorage.setItem(key, JSON.stringify(positions));
  } catch {
    // localStorage can be unavailable in private browsing or test environments.
  }
}

/** Obsidian's node radius: max(8, min(3·√(links+1), 30)) in layout units. */
function nodeRadius(node: KnowledgeGraphNode): number {
  return clamp(3 * Math.sqrt(Math.max(0, node.degree) + 1), 8, 30) * (node.ghost ? 0.75 : 1);
}

function overlapRepair(cy: Core): void {
  const nodes = cy.nodes(':visible').not('[?isGroup]').toArray() as NodeSingular[];
  // Safety net after the simulation: boxes are the circle plus its label as drawn now (labels keep
  // their screen size, so they are larger in layout units when zoomed out), with a gap in pixels.
  // Overlapping pairs move apart along the axis of least overlap.
  const gap = LABEL_SPACE / 3 / cy.zoom();
  const boxes = nodes.map((node) => {
    const box = node.boundingBox({ includeLabels: true, includeOverlays: false });
    const p = node.position();
    return { dx: (box.x1 + box.x2) / 2 - p.x, dy: (box.y1 + box.y2) / 2 - p.y, w: box.w, h: box.h };
  });
  for (let pass = 0; pass < 120; pass += 1) {
    let moved = false;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const pa = a.position();
        const pb = b.position();
        const dx = pb.x + boxes[j].dx - (pa.x + boxes[i].dx);
        const dy = pb.y + boxes[j].dy - (pa.y + boxes[i].dy);
        const overlapX = (boxes[i].w + boxes[j].w) / 2 + gap - Math.abs(dx);
        const overlapY = (boxes[i].h + boxes[j].h) / 2 + gap - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        const sign = (value: number, salt: string) => (value !== 0 ? Math.sign(value) : hash(salt) % 2 ? 1 : -1);
        if (overlapX < overlapY) {
          const shift = (overlapX / 2 + 1) * sign(dx, `${a.id()}${b.id()}x`);
          a.position({ x: pa.x - shift, y: pa.y });
          b.position({ x: pb.x + shift, y: pb.y });
        } else {
          const shift = (overlapY / 2 + 1) * sign(dy, `${a.id()}${b.id()}y`);
          a.position({ x: pa.x, y: pa.y - shift });
          b.position({ x: pb.x, y: pb.y + shift });
        }
        moved = true;
      }
    }
    if (!moved) break;
  }
}

function neighboursAt(cy: Core, id: string, depth: number): Set<string> {
  const found = new Set<string>([id]);
  let frontier = new Set<string>([id]);
  for (let level = 0; level < depth; level += 1) {
    const next = new Set<string>();
    frontier.forEach((nodeId) => {
      cy.getElementById(nodeId)
        .connectedEdges()
        .forEach((edge) => {
          const other = edge.source().id() === nodeId ? edge.target().id() : edge.source().id();
          if (!found.has(other)) next.add(other);
        });
    });
    next.forEach((nodeId) => found.add(nodeId));
    frontier = next;
  }
  return found;
}

export function createGraphEngine(
  container: GraphContainer,
  data: KnowledgeGraphResponse,
  options: GraphEngineOptions,
  labels: LabelLayer,
): GraphController {
  let currentData = data;
  let mode = options.mode;
  let depth = options.depth;
  let selectedEdgesOnly = options.selectedEdgesOnly;
  let selectedId: string | null = null;
  let hoveredId: string | null = null;
  let labelTimer: ReturnType<typeof setTimeout> | undefined;
  let saved = readPositions(options.storageKey);
  let size = { width: 0, height: 0 };
  let lastWindow = { width: window.innerWidth, height: window.innerHeight };

  const colors = {
    background: cssColor('--bg-canvas', GRAPH_COLORS.background),
    strong: cssColor('--border-strong', GRAPH_COLORS.nodeStrong),
    muted: cssColor('--text-muted', GRAPH_COLORS.label),
    primary: cssColor('--text-primary', GRAPH_COLORS.label),
    node: cssColor('--text-muted', GRAPH_COLORS.nodeStrong),
    border: cssColor('--border-default', GRAPH_COLORS.edge),
    accent: cssColor('--accent', GRAPH_COLORS.accent),
  };

  const buildElements = (graph: KnowledgeGraphResponse): ElementDefinition[] => {
    const groups = new Map(graph.nodes.map((node) => [node.id, groupName(node)]));
    const elements: ElementDefinition[] = [...new Set(groups.values())].map((id) => ({
      data: { id, label: id.replace(/^(project:|folder:)/, ''), isGroup: true },
    }));
    graph.nodes.forEach((node) => {
      const group = groups.get(node.id) ?? 'folder:Общее';
      const radius = nodeRadius(node);
      elements.push({
        data: {
          id: node.id,
          label: '',
          title: node.title,
          fullLabel: node.title,
          degree: node.degree,
          radius,
          d: radius * 2,
          fs: LABEL_PX,
          ow: 2,
          tm: 4,
          bw: 1,
          ghost: node.ghost ? 'true' : 'false',
          group,
          // Compound parents only in the "projects" mode: hiding a parent hides its children.
          ...(mode === 'projects' ? { parent: group } : {}),
        },
        position: saved[node.id] ?? { x: 0, y: 0 },
        classes: node.ghost ? 'ghost' : '',
      });
    });
    graph.edges.forEach((edge, index) => {
      elements.push({
        data: {
          id: `${edge.source}--${edge.target}--${edge.type ?? 'edge'}--${index}`,
          source: edge.source,
          target: edge.target,
          type: edge.type ?? 'wiki',
          w: 1,
        },
      });
    });
    return elements;
  };

  const cy = cytoscape({
    container,
    // Without an explicit layout Cytoscape runs 'grid' on init and discards the given positions.
    layout: { name: 'preset' },
    elements: buildElements(currentData),
    minZoom: 0.02,
    maxZoom: 8,
    style: [
      {
        selector: 'node[?isGroup]',
        style: {
          label: 'data(label)',
          'background-color': colors.background,
          'background-opacity': 0.01,
          'border-color': colors.strong,
          'border-width': '1px',
          shape: 'round-rectangle',
          padding: '40px',
          color: colors.muted,
          'font-size': '14px',
          'min-zoomed-font-size': 6,
          'text-valign': 'top',
          'text-margin-y': -12,
        },
      },
      {
        selector: 'node[!isGroup]',
        style: {
          label: 'data(label)',
          'background-color': colors.node,
          color: colors.primary,
          'text-outline-color': colors.background,
          'text-outline-width': 'data(ow)',
          // Labels sit under the node at a constant screen size (fs is 12 px divided by the zoom);
          // the label layer measures exactly this box to avoid overlaps.
          'font-family': LABEL_FONT_FAMILY,
          'font-size': 'data(fs)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 'data(tm)' as unknown as number,
          'text-wrap': 'none',
          width: 'data(d)',
          height: 'data(d)',
          shape: 'ellipse',
          'border-width': 0,
        },
      },
      {
        selector: 'node.ghost',
        style: {
          'background-color': colors.background,
          'border-color': colors.strong,
          'border-width': 'data(bw)',
          'border-style': 'dashed',
          opacity: 0.6,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 'data(w)',
          'line-color': colors.strong,
          opacity: 0.35,
          'curve-style': 'straight',
        },
      },
      { selector: 'edge[type = "embed"]', style: { 'line-style': 'dashed' } },
      { selector: 'edge.neighbour-edge', style: { opacity: 0.6 } },
      {
        selector: 'node.selected',
        style: {
          'background-color': colors.accent,
          'border-color': colors.accent,
          'border-width': 0,
          opacity: 1,
          'z-index': 10,
        },
      },
      { selector: 'node.neighbour', style: { opacity: 1 } },
      { selector: 'edge.active-edge', style: { 'line-color': colors.accent, opacity: 0.95 } },
      { selector: 'node.hovered', style: { 'background-color': colors.primary, 'z-index': 10 } },
      { selector: 'edge.hover-edge', style: { 'line-color': colors.primary, opacity: 0.8 } },
      { selector: '.dimmed', style: { opacity: 0.1 } },
      { selector: '.faded', style: { opacity: 0.2 } },
    ],
  });

  // Like Obsidian (nodeScale = √(1/zoom)): zooming out shrinks circles slower than distances, so
  // a far view stays a field of dots instead of vanishing; labels and edges keep their screen size.
  const applyScale = () => {
    const zoom = cy.zoom();
    const nodeScale = Math.sqrt(1 / zoom);
    cy.batch(() => {
      cy.nodes('[!isGroup]').forEach((node) => {
        node.data({
          d: node.data('radius') * 2 * nodeScale,
          fs: LABEL_PX / zoom,
          ow: 2 / zoom,
          tm: 4 / zoom,
          bw: 1 / zoom,
        });
      });
      cy.edges().data('w', 1 / zoom);
    });
  };

  // --- Simulation (Obsidian's forces) ---
  let simNodes: SimNode[] = [];
  let simulation: Simulation<SimNode, SimLink> | null = null;
  const groupCenters = new Map<string, { x: number; y: number }>();

  const buildSimulation = () => {
    simulation?.stop();
    const notes = cy.nodes('[!isGroup]');
    simNodes = notes.map((node) => {
      const position = saved[node.id()];
      // Without a saved position d3 places nodes on its deterministic phyllotaxis spiral.
      return {
        id: node.id(),
        group: String(node.data('group')),
        ...(position ? { x: position.x, y: position.y } : {}),
      };
    });
    const ids = new Set(simNodes.map((node) => node.id));
    const links: SimLink[] = currentData.edges
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.source !== edge.target)
      .map((edge) => ({ source: edge.source, target: edge.target }));
    const groups = [...new Set(simNodes.map((node) => node.group))].sort();
    const ring = 160 * Math.sqrt(simNodes.length);
    groupCenters.clear();
    groups.forEach((group, index) => {
      const angle = (index / Math.max(1, groups.length)) * Math.PI * 2;
      groupCenters.set(
        group,
        groups.length > 1 ? { x: Math.cos(angle) * ring, y: Math.sin(angle) * ring } : { x: 0, y: 0 },
      );
    });
    // In the projects mode each group is pulled to its own spot on a ring, so frames do not overlap.
    const grouped = mode === 'projects';
    const center = (axis: 'x' | 'y') => (node: SimNode) => (grouped ? (groupCenters.get(node.group)?.[axis] ?? 0) : 0);
    const radius = (node: SimNode) => Number(cy.getElementById(node.id).data('radius')) || 8;
    // Obsidian's centre force is the same on both axes, which gives a round cloud; in a wide panel
    // that left the sides empty. Pull harder vertically by the canvas aspect so the cloud fills it.
    const aspect = clamp((container.clientWidth || 1) / (container.clientHeight || 1), 0.5, 2.5);
    const centerX = OBSIDIAN.centerStrength / Math.sqrt(aspect);
    const centerY = OBSIDIAN.centerStrength * Math.sqrt(aspect);
    simulation = forceSimulation<SimNode, SimLink>(simNodes)
      .velocityDecay(OBSIDIAN.velocityDecay)
      .force('x', forceX<SimNode>(center('x')).strength(grouped ? 0.3 : centerX))
      .force('y', forceY<SimNode>(center('y')).strength(grouped ? 0.3 : centerY))
      .force(
        'link',
        forceLink<SimNode, SimLink>(links)
          .id((node) => node.id)
          .distance(OBSIDIAN.linkDistance)
          .strength((link) => {
            // Links across groups are weaker in the projects mode so clusters stay apart.
            const source = link.source as SimNode;
            const target = link.target as SimNode;
            const base = 1 / Math.max(1, Math.min(degreeOf(source.id), degreeOf(target.id)));
            return grouped && source.group !== target.group ? base * 0.1 : base;
          }),
      )
      .force('charge', forceManyBody<SimNode>().strength(OBSIDIAN.repel).distanceMin(OBSIDIAN.repelDistanceMin))
      .force(
        'collide',
        forceCollide<SimNode>((node) => Math.max(OBSIDIAN.collideRadius, radius(node) + LABEL_SPACE)).strength(
          OBSIDIAN.collideStrength,
        ),
      )
      .stop();
    simulation.on('tick', pushPositions);
    simulation.on('end', () => {
      writePositions(options.storageKey, cy);
      saved = readPositions(options.storageKey);
      applyLabels();
    });
  };
  const degreeOf = (id: string) => cy.getElementById(id).degree(false) || 1;
  const pushPositions = () => {
    const grabbed = cy.nodes(':grabbed');
    cy.batch(() => {
      simNodes.forEach((node) => {
        const element = cy.getElementById(node.id);
        if (grabbed.contains(element)) return;
        element.position({ x: node.x ?? 0, y: node.y ?? 0 });
      });
    });
    applyLabels();
  };
  const settle = () => {
    if (!simulation) return;
    simulation.alpha(1);
    for (let tick = 0; tick < SETTLE_TICKS; tick += 1) simulation.tick();
    simulation.alpha(0);
    pushPositions();
    repair();
  };
  const repair = () => {
    // Labels first: the boxes being separated include the labels that are actually shown.
    labels.apply(cy, { selectedId, hoveredId });
    overlapRepair(cy);
    // Feed the repaired positions back so a later drag starts from what is on screen.
    simNodes.forEach((node) => {
      const position = cy.getElementById(node.id).position();
      node.x = position.x;
      node.y = position.y;
      node.vx = 0;
      node.vy = 0;
    });
  };

  const applyLabels = () => {
    if (labelTimer) clearTimeout(labelTimer);
    labelTimer = setTimeout(() => labels.apply(cy, { selectedId, hoveredId }), 60);
  };
  const applyHover = () => {
    cy.elements().removeClass('hovered hover-edge faded');
    // Obsidian highlights the hovered note's neighbourhood; with a selection, the selection rules.
    if (!hoveredId || selectedId) return;
    const node = cy.getElementById(hoveredId);
    if (node.empty()) return;
    cy.elements().not('[?isGroup]').addClass('faded');
    node.closedNeighborhood().removeClass('faded');
    node.addClass('hovered');
    node.connectedEdges().addClass('hover-edge');
  };
  const applyState = () => {
    cy.elements().removeClass('dimmed active-edge neighbour neighbour-edge').style('display', 'element');
    cy.nodes().removeClass('selected');
    if (!selectedId) cy.nodes(':selected').unselect();
    cy.nodes('[?isGroup]').style('display', mode === 'projects' ? 'element' : 'none');
    if (mode === 'focus' && !selectedId) {
      const top = cy
        .nodes(':visible')
        .not('[?isGroup]')
        .sort((a, b) => b.data('degree') - a.data('degree'))
        .first();
      selectedId = top.empty() ? null : top.id();
    }
    if (!selectedId) {
      if (mode === 'focus') cy.nodes(':visible').not('[?isGroup]').style('display', 'none');
      applyHover();
      applyLabels();
      return;
    }
    const selected = cy.getElementById(selectedId);
    if (selected.empty()) return;
    // Native selection too, so tools and tests reading :selected see what the user selected.
    cy.nodes(':selected').unselect();
    selected.select();
    const visible = neighboursAt(cy, selectedId, depth);
    selected.addClass('selected');
    selected.neighborhood('node').addClass('neighbour');
    selected.connectedEdges().addClass('active-edge');
    cy.edges().forEach((edge) => {
      if (visible.has(edge.source().id()) && visible.has(edge.target().id())) edge.addClass('neighbour-edge');
    });
    cy.nodes(':visible')
      .not('[?isGroup]')
      .forEach((node) => {
        const inFocus = visible.has(node.id());
        if (mode === 'focus' && !inFocus) node.style('display', 'none');
        else if (!inFocus) node.addClass('dimmed');
      });
    cy.edges().forEach((edge) => {
      const incident = edge.source().id() === selectedId || edge.target().id() === selectedId;
      if (selectedEdgesOnly && !incident) edge.style('display', 'none');
      else if (!incident) edge.addClass('dimmed');
    });
    applyHover();
    applyLabels();
  };
  const fitNow = () => {
    cy.fit(cy.elements(':visible'), FIT_PADDING);
    applyScale();
  };
  const layout = (fit: boolean) => {
    buildSimulation();
    const notes = cy.nodes('[!isGroup]');
    const allSaved = notes.length > 0 && (notes.toArray() as NodeSingular[]).every((node) => Boolean(saved[node.id()]));
    // Saved positions are the user's layout: never run the simulation over them. New notes settle
    // around the saved ones, which stay fixed for that run.
    if (!allSaved) {
      simNodes.forEach((node) => {
        const position = saved[node.id];
        if (position) {
          node.fx = position.x;
          node.fy = position.y;
        }
      });
      settle();
      simNodes.forEach((node) => {
        node.fx = null;
        node.fy = null;
      });
      writePositions(options.storageKey, cy);
      saved = readPositions(options.storageKey);
    }
    applyState();
    if (fit) {
      fitNow();
      if (!allSaved) {
        // Circles are drawn bigger when zoomed out (√(1/zoom)); separate them at the size they
        // are actually shown, then fit again. Two rounds converge: the zoom barely changes.
        for (let round = 0; round < 2; round += 1) {
          repair();
          fitNow();
        }
        writePositions(options.storageKey, cy);
        saved = readPositions(options.storageKey);
      }
    } else applyScale();
    container.dataset.ready = '1';
    container.__kg = controller;
    applyLabels();
  };

  const resizeObserver = new ResizeObserver(() => {
    const next = { width: container.clientWidth, height: container.clientHeight };
    if (!next.width || !next.height) return;
    cy.stop(true, true);
    cy.resize();
    // Opening the side panel narrows the canvas: pan and zoom stay, so every node keeps its place on
    // screen (re-fitting here made the whole graph jump on every click). A resized browser window is
    // a different thing: then the graph is fitted into the new canvas.
    const windowSize = { width: window.innerWidth, height: window.innerHeight };
    const windowChanged = windowSize.width !== lastWindow.width || windowSize.height !== lastWindow.height;
    lastWindow = windowSize;
    if (!size.width || !size.height || windowChanged) fitNow();
    size = next;
    applyLabels();
  });
  resizeObserver.observe(container);
  // On zoom the sizes and the labels change at once: a stale label set would collide for a frame.
  cy.on('zoom', () => {
    applyScale();
    labels.apply(cy, { selectedId, hoveredId });
  });
  cy.on('pan', applyLabels);

  // Dragging works like Obsidian: the node follows the pointer, the simulation wakes up and the
  // neighbours follow. The dropped node stays where it was put; everything settles and is saved.
  cy.on('grab', 'node[!isGroup]', (event) => {
    const node = simNodes.find((item) => item.id === event.target.id());
    if (!node || !simulation) return;
    const position = event.target.position();
    node.fx = position.x;
    node.fy = position.y;
    simulation.alphaTarget(OBSIDIAN.dragAlphaTarget).restart();
  });
  cy.on('drag', 'node[!isGroup]', (event) => {
    const node = simNodes.find((item) => item.id === event.target.id());
    if (!node) return;
    const position = event.target.position();
    node.fx = position.x;
    node.fy = position.y;
  });
  cy.on('free', 'node[!isGroup]', () => {
    simulation?.alphaTarget(0);
  });
  cy.on('dragfree', 'node[!isGroup]', () => {
    writePositions(options.storageKey, cy);
    saved = readPositions(options.storageKey);
    applyLabels();
  });
  cy.on('mouseover', 'node[!isGroup]', (event) => {
    hoveredId = event.target.id();
    applyHover();
    applyLabels();
  });
  cy.on('mouseout', 'node[!isGroup]', () => {
    hoveredId = null;
    applyHover();
    applyLabels();
  });
  cy.on('tap', 'node[!isGroup]', (event) => {
    selectedId = event.target.id();
    options.onSelect(selectedId);
    applyState();
  });
  cy.on('tap', (event) => {
    if (event.target === cy) {
      selectedId = null;
      options.onSelect(null);
      applyState();
    }
  });
  cy.on('dbltap', 'node[!isGroup]', (event) => options.onOpen(event.target.id()));

  const controller: GraphController = {
    cy,
    setMode(next) {
      const groupingChanged = (next === 'projects') !== (mode === 'projects');
      mode = next;
      if (groupingChanged) {
        // An explicit mode switch (not a click): regroup and lay out once.
        cy.nodes('[!isGroup]').forEach((node) => {
          node.move({ parent: mode === 'projects' ? node.data('group') : null });
        });
        saved = {};
        layout(true);
        return;
      }
      applyState();
      cy.animate({ fit: { eles: cy.elements(':visible'), padding: FIT_PADDING } }, { duration: 220 });
    },
    setDepth(next) {
      depth = next;
      applyState();
    },
    setSelectedEdgesOnly(next) {
      selectedEdgesOnly = next;
      applyState();
    },
    select(id) {
      // The shell echoes taps back as props; re-selecting the same node must not move the camera.
      if (id === selectedId) return;
      selectedId = id;
      // Selected from the list or search: bring it into view only if it is off-screen.
      if (id) {
        const node = cy.getElementById(id);
        const box = cy.extent();
        const p = node.position();
        if (node.nonempty() && (p.x < box.x1 || p.x > box.x2 || p.y < box.y1 || p.y > box.y2))
          cy.animate({ center: { eles: node } }, { duration: 180 });
      }
      applyState();
    },
    fit() {
      cy.stop(true, true);
      cy.animate({ fit: { eles: cy.elements(':visible'), padding: FIT_PADDING } }, { duration: 220 });
    },
    resetLayout() {
      saved = {};
      try {
        localStorage.removeItem(options.storageKey);
      } catch {
        /* ignore */
      }
      layout(true);
    },
    update(next) {
      writePositions(options.storageKey, cy);
      saved = readPositions(options.storageKey);
      currentData = next;
      cy.elements().remove();
      cy.add(buildElements(next));
      layout(false);
    },
    destroy() {
      simulation?.stop();
      resizeObserver.disconnect();
      if (labelTimer) clearTimeout(labelTimer);
      delete container.__kg;
      delete container.dataset.ready;
      cy.destroy();
    },
  };
  size = { width: container.clientWidth, height: container.clientHeight };
  layout(true);
  return controller;
}
