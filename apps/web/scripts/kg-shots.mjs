// Knowledge graph acceptance screenshots.
// Usage: node scripts/kg-shots.mjs [output-dir], from apps/web.
import { mkdirSync, readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const base = process.env.AIHUB_DEV_URL ?? 'http://127.0.0.1:58093';
const output = process.argv[2] ?? 'test-results/kg-shots';
const password =
  process.env.AIHUB_E2E_ADMIN_PASSWORD ??
  readFileSync(process.env.AIHUB_DEV_CREDS ?? '../../scripts/dev/.dev-users', 'utf8').match(
    /^admin=(.*)$/m,
  )?.[1] ??
  '';
mkdirSync(output, { recursive: true });

function dataset(nodes, edges, seed) {
  const random = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const result = { nodes: [], edges: [] };
  for (let i = 0; i < nodes; i += 1)
    result.nodes.push({
      id: `shot-${seed}-${i}`,
      title: `Synthetic knowledge note ${i} — long project and folder name for readability verification`,
      path: `research/shot-${i}.md`,
      project_id: `project-${i % 5}`,
      degree: 0,
      ghost: i >= nodes - Math.max(3, Math.round(nodes * 0.04)),
      type: 'markdown',
    });
  const keys = new Set();
  while (result.edges.length < edges) {
    const source = Math.floor(random() * nodes);
    const target = Math.floor(random() * nodes);
    const key = `${Math.min(source, target)}:${Math.max(source, target)}`;
    if (source === target || keys.has(key)) continue;
    keys.add(key);
    result.edges.push({
      source: result.nodes[source].id,
      target: result.nodes[target].id,
      type: result.edges.length % 4 ? 'wiki' : 'embed',
    });
    result.nodes[source].degree += 1;
    result.nodes[target].degree += 1;
  }
  return result;
}

async function login(page) {
  await page.goto(`${base}/login`);
  await page.getByLabel('Пользователь').fill('admin');
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
}

async function capture(page, label, data) {
  if (data)
    await page.route('**/api/v0/knowledge/graph', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) }),
    );
  await page.goto(`${base}/knowledge`);
  await page.getByRole('button', { name: 'Граф' }).click();
  const canvas = page.locator('.knowledge-graph-canvas');
  await canvas.waitFor({ state: 'visible' });
  await page.waitForTimeout(900);
  const controller = await canvas.evaluate((element) => (element.__kg ? true : false));
  if (!controller) throw new Error(`${label}: container.__kg is unavailable`);
  const shots = async (state) => page.screenshot({ path: `${output}/${label}-${state}.png`, fullPage: true });
  await shots('open-1440');
  const id = await canvas.evaluate((element) => element.__kg.cy.nodes(':visible').first().id());
  await canvas.evaluate((element, nodeId) => element.__kg.select(nodeId), id);
  await page.waitForTimeout(250);
  await shots('selected-1440');
  await canvas.evaluate((element) => element.__kg.setMode('focus'));
  await page.waitForTimeout(250);
  await shots('focus-1440');
  await canvas.evaluate((element) => element.__kg.cy.zoom({ level: 0.45, renderedPosition: { x: 100, y: 100 } }));
  await shots('remote-1440');
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(300);
  await shots('remote-1920');
  await canvas.evaluate((element) => element.__kg.setMode('overview'));
  await shots('overview-1920');
  console.log(`${label}: 6 screenshots`);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await login(page);
await capture(page, 'real', undefined);
await capture(page, 'synthetic-100x300', dataset(100, 300, 1003));
await capture(page, 'synthetic-300x1000', dataset(300, 1000, 3007));
await browser.close();
