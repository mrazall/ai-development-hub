/* eslint-disable @typescript-eslint/no-explicit-any -- probes run inside the page against the untyped Cytoscape instance */
import { expect, test, type Page } from '@playwright/test';
import { graph100x300, graph300x1000, type KnowledgeGraphResponse } from './fixtures/graph-datasets';

const password = process.env.AIHUB_E2E_ADMIN_PASSWORD ?? '';
async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

async function openGraph(page: Page, data?: KnowledgeGraphResponse): Promise<void> {
  await login(page);
  if (data) {
    await page.route('**/api/v0/knowledge/graph', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) }),
    );
    await page.route('**/api/v0/knowledge/documents**', async (route) => {
      const url = new URL(route.request().url());
      const id = url.pathname.split('/').pop() ?? '';
      const node = data.nodes.find((item) => item.id === id) ?? data.nodes[0];
      const item = {
        id: node.id,
        title: node.title,
        path: node.path ?? `${node.id}.md`,
        project_id: node.project_id,
        type: node.type ?? 'markdown',
        updated_at: '2026-10-25T00:00:00Z',
        excerpt: 'synthetic browser fixture',
      };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          url.pathname !== '/api/v0/knowledge/documents' && id
            ? { ...item, content: '# Synthetic note', visibility: 'private' }
            : {
                items: data.nodes.slice(0, 50).map((n) => ({
                  ...item,
                  id: n.id,
                  title: n.title,
                  path: n.path ?? `${n.id}.md`,
                  project_id: n.project_id,
                })),
                total: data.nodes.length,
                offset: 0,
                limit: 50,
              },
        ),
      });
    });
  }
  await page.goto('/knowledge');
  await page.getByRole('button', { name: 'Граф' }).click();
  await expect(page.locator('.knowledge-graph-canvas')).toHaveAttribute('data-ready', '1');
}

async function evaluateGraph(page: Page) {
  return page.locator('.knowledge-graph-canvas').evaluate((element) => {
    const container = element as HTMLDivElement & { __kg?: { cy: any; select: (id: string) => void } };
    const cy = container.__kg?.cy;
    if (!cy) throw new Error('Graph contract missing: container.__kg.cy');
    const visible = cy.nodes(':visible');
    const boxes = visible.map((node: any) => node.boundingBox());
    const labels = visible
      .filter((node: any) => String(node.data('label') ?? '').trim())
      .map((node: any) => node.renderedBoundingBox({ includeNodes: false, includeLabels: true }));
    const intersects = (a: any, b: any) => a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
    const overlapCount = (items: any[]) =>
      items.reduce(
        (count, item, index) => count + items.slice(index + 1).filter((other) => intersects(item, other)).length,
        0,
      );
    const extent = cy.extent();
    const inside = visible.every((node: any) => {
      const p = node.position();
      return p.x >= extent.x1 && p.x <= extent.x2 && p.y >= extent.y1 && p.y <= extent.y2;
    });
    const bb = visible.boundingBox();
    const occupied = (bb.w * bb.h) / Math.max(1, (extent.x2 - extent.x1) * (extent.y2 - extent.y1));
    return {
      nodeOverlaps: overlapCount(boxes),
      labelOverlaps: overlapCount(labels),
      inside,
      occupied,
      // The most connected note: an isolated one has no edges to highlight.
      firstId: visible.max((node: any) => node.degree(false)).ele.id(),
      edgeCount: cy.edges().length,
    };
  });
}

async function checkDataset(page: Page, data?: KnowledgeGraphResponse): Promise<void> {
  await openGraph(page, data);
  const initial = await evaluateGraph(page);
  expect(initial.nodeOverlaps).toBe(0);
  expect(initial.labelOverlaps).toBe(0);
  expect(initial.inside).toBeTruthy();
  expect(initial.occupied).toBeGreaterThanOrEqual(0.4);

  const id = initial.firstId;
  const canvas = page.locator('.knowledge-graph-canvas');
  const beforeSelection = await canvas.evaluate((element) =>
    (element as any).__kg.cy.nodes().map((node: any) => ({ id: node.id(), position: node.position() })),
  );
  await canvas.evaluate((element, nodeId) => (element as any).__kg.select(nodeId), id);
  await expect.poll(() => canvas.locator('canvas').count()).toBeGreaterThan(0);
  const selection = await canvas.evaluate((element, nodeId) => {
    const cy = (element as any).__kg.cy;
    const node = cy.getElementById(nodeId);
    return {
      isAccent:
        String(node.style('border-color')).replace(/\s/g, '').toLowerCase().includes('230,184,91') ||
        String(node.style('border-color')).toLowerCase().includes('e6b85b'),
      active: node.connectedEdges().filter((edge: any) => edge.style('opacity') >= 0.9).length,
      muted: cy.edges().filter((edge: any) => edge.style('opacity') < 0.9).length,
    };
  }, id);
  expect(selection.isAccent).toBeTruthy();
  expect(selection.active).toBeGreaterThan(0);
  expect(selection.muted).toBeGreaterThan(0);
  const afterSelection = await canvas.evaluate((element) =>
    (element as any).__kg.cy.nodes().map((node: any) => ({ id: node.id(), position: node.position() })),
  );
  expect(afterSelection).toEqual(beforeSelection);

  // Zoom checks start from the fitted view (selection centres the camera on the node).
  await canvas.evaluate((element) => (element as any).__kg.fit());
  await page.waitForTimeout(400);
  const beforeZoom = (await evaluateGraph(page)).labelOverlaps;
  await canvas.evaluate((element) =>
    // Zoom out relative to the fitted view (a fixed level zoomed *in* on large graphs).
    (element as any).__kg.cy.zoom({
      level: (element as any).__kg.cy.zoom() * 0.6,
      renderedPosition: {
        x: (element as any).__kg.cy.width() / 2,
        y: (element as any).__kg.cy.height() / 2,
      },
    }),
  );
  const afterZoom = await evaluateGraph(page);
  expect(afterZoom.labelOverlaps).toBe(0);
  expect(afterZoom.inside).toBeTruthy();
  expect(afterZoom.labelOverlaps).toBeLessThanOrEqual(beforeZoom);

  await page.setViewportSize({ width: 1024, height: 860 });
  await expect.poll(() => evaluateGraph(page).then((result) => result.inside)).toBeTruthy();
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect.poll(() => evaluateGraph(page).then((result) => result.inside)).toBeTruthy();

  await canvas.evaluate((element) => {
    const controller = (element as any).__kg;
    controller.setMode('focus');
  });
  await expect
    .poll(() => canvas.evaluate((element) => (element as any).__kg.cy.nodes(':visible').length))
    .toBeGreaterThan(0);
  const focusIds = await canvas.evaluate((element) => {
    const cy = (element as any).__kg.cy;
    const selected = cy.$(':selected').first();
    const allowed = new Set([selected.id(), ...selected.neighborhood('node').map((node: any) => node.id())]);
    return { visible: cy.nodes(':visible').map((node: any) => node.id()), allowed: [...allowed] };
  });
  expect(focusIds.visible.every((nodeId: string) => focusIds.allowed.includes(nodeId))).toBeTruthy();
  await canvas.evaluate((element) => {
    const controller = (element as any).__kg;
    controller.setMode('overview');
  });
  await page.waitForTimeout(400); // the mode switch animates a fit; grab the node after it settles

  // Drag the node itself: rendered positions are canvas-relative, the mouse works in page coordinates.
  const box = await canvas.boundingBox();
  if (!box) throw new Error('graph canvas has no box');
  const grab = await canvas.evaluate((element, nodeId) => {
    const node = (element as any).__kg.cy.getElementById(nodeId);
    return { rendered: node.renderedPosition(), model: { ...node.position() } };
  }, id);
  await page.mouse.move(box.x + grab.rendered.x, box.y + grab.rendered.y);
  await page.mouse.down();
  await page.mouse.move(box.x + grab.rendered.x + 30, box.y + grab.rendered.y + 20, { steps: 6 });
  await page.mouse.up();
  const moved = await canvas.evaluate(
    (element, nodeId) => ({ ...(element as any).__kg.cy.getElementById(nodeId).position() }),
    id,
  );
  expect(Math.abs(moved.x - grab.model.x) + Math.abs(moved.y - grab.model.y)).toBeGreaterThan(2);
  await page.reload();
  await expect(canvas).toHaveAttribute('data-ready', '1');
  const restored = await canvas.evaluate(
    (element, nodeId) => ({ ...(element as any).__kg.cy.getElementById(nodeId).position() }),
    id,
  );
  expect(Math.abs(restored.x - moved.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(restored.y - moved.y)).toBeLessThanOrEqual(2);
  // Like a person on a dense graph: zoom in on the note before double-clicking it.
  const target = await canvas.evaluate((element, nodeId) => {
    const cy = (element as any).__kg.cy;
    const node = cy.getElementById(nodeId);
    cy.zoom({ level: Math.max(cy.zoom(), 1), position: node.position() });
    cy.center(node);
    return node.renderedPosition();
  }, id);
  await page.waitForTimeout(150);
  await canvas.dblclick({ position: { x: target.x, y: target.y } });
  await expect(page.locator('.knowledge-graph-inspector')).toBeVisible();
}

test.describe('knowledge graph readability contract', () => {
  test.beforeAll(() => expect(password, 'AIHUB_E2E_ADMIN_PASSWORD is required').not.toBe(''));
  test('real user graph', async ({ page }) => checkDataset(page));
  test('synthetic 100 nodes / 300 edges', async ({ page }) => checkDataset(page, graph100x300));
  test('synthetic 300 nodes / 1000 edges', async ({ page }) => checkDataset(page, graph300x1000));
});
