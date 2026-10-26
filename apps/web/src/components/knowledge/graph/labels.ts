import type { NodeSingular } from 'cytoscape';
import type { LabelLayer } from './types';

const MAX_LABEL_LENGTH = 22;
// How many labels fit depends on the canvas, not on the zoom level: collisions drop the rest,
// so zooming out (nodes closer on screen) hides secondary labels by itself.
const MIN_LABELS = 6;
const MAX_LABELS = 20;
const PX_PER_LABEL = 45_000;
// Must match the node label style in engine.ts (font, size, label under the node, 4 px margin).
export const LABEL_FONT_FAMILY = 'Inter, "Segoe UI", system-ui, sans-serif';
const LABEL_FONT = `12px ${LABEL_FONT_FAMILY}`;

const shorten = (value: string) =>
  value.length > MAX_LABEL_LENGTH ? `${value.slice(0, MAX_LABEL_LENGTH - 1).trimEnd()}…` : value;

function rectFor(node: NodeSingular, text: string, ctx: CanvasRenderingContext2D | null) {
  const measured = ctx ? ctx.measureText(text).width : text.length * 7;
  const position = node.renderedPosition();
  const radius = Math.max(node.renderedWidth(), node.renderedHeight()) / 2;
  return {
    left: position.x - measured / 2 - 4,
    right: position.x + measured / 2 + 4,
    top: position.y + radius + 2,
    bottom: position.y + radius + 20,
  };
}

const intersects = (a: ReturnType<typeof rectFor>, b: ReturnType<typeof rectFor>) =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

export const labelLayer: LabelLayer = {
  apply(cy, { selectedId, hoveredId }) {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (context) context.font = LABEL_FONT;
    const nodes = cy.nodes(':visible').filter((node) => !node.data('isGroup'));
    const selected = selectedId ? cy.getElementById(selectedId) : cy.collection();
    const hovered = hoveredId ? cy.getElementById(hoveredId) : cy.collection();
    const neighbours = selected.empty() ? cy.collection() : selected.neighborhood('node');
    const degree = (node: NodeSingular) => Number(node.data('degree') ?? node.degree());
    const nodeList = nodes.toArray() as NodeSingular[];
    const important = nodeList.sort((a, b) => degree(b) - degree(a));
    const ordered = [
      ...(selected.toArray() as NodeSingular[]),
      ...(neighbours.toArray() as NodeSingular[]),
      ...(hovered.toArray() as NodeSingular[]),
      ...important,
      ...nodeList,
    ].filter((node, index, list) => list.findIndex((item) => item.id() === node.id()) === index);
    const limit = Math.max(MIN_LABELS, Math.min(MAX_LABELS, Math.round((cy.width() * cy.height()) / PX_PER_LABEL)));
    const shown: ReturnType<typeof rectFor>[] = [];
    const nodeRects = nodeList.map((node) => ({
      left: node.renderedPosition().x - node.renderedWidth() / 2 - 3,
      right: node.renderedPosition().x + node.renderedWidth() / 2 + 3,
      top: node.renderedPosition().y - node.renderedHeight() / 2 - 3,
      bottom: node.renderedPosition().y + node.renderedHeight() / 2 + 3,
    }));
    nodes.data('label', '');
    ordered.forEach((node, index) => {
      if (index >= limit && !node.same(selected) && !node.same(hovered) && !neighbours.contains(node)) return;
      const text = shorten(String(node.data('title') ?? node.data('fullLabel') ?? node.id()));
      const rect = rectFor(node, text, context);
      const collides =
        shown.some((item) => intersects(rect, item)) ||
        nodeRects.some(
          (item, rectIndex) =>
            intersects(rect, item) &&
            item !== nodeRects[nodeList.indexOf(node)] &&
            rectIndex !== nodeList.indexOf(node),
        );
      if (!collides) {
        node.data('label', text);
        shown.push(rect);
      }
    });
  },
};
