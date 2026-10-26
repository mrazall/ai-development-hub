// Nodes logo: every brand asset from one geometry. Usage (from apps/web): node scripts/brand-assets.mjs
// The outputs are committed; the build does not regenerate them.
// Writes SVGs, PNG icons (rendered by Chromium), favicon.ico and the preview sheet into public/.
import { mkdirSync, writeFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const PUBLIC = 'public';
const BRAND = `${PUBLIC}/brand`;
mkdirSync(BRAND, { recursive: true });
mkdirSync(`${PUBLIC}/icons`, { recursive: true });

export const COLORS = {
  background: '#141414',
  node: '#F0F0ED',
  accent: '#E6B85B',
  line: '#A6A6A1',
  // On light backgrounds the stock amber is ~1.8:1; a deeper amber keeps the coordinator visible.
  lightNode: '#1F1F1E',
  lightAccent: '#B07A1E',
  lightLine: '#8A8A85',
};

// Simplified Mark, 64 grid (32 px and up). Lines end at the centres and hide under the circles.
const FULL = {
  size: 64,
  stroke: 2.5,
  nodes: { top: [43, 11, 7], left: [17, 25, 7], bottom: [24, 49, 7], center: [46, 39, 9] },
  links: [
    ['left', 'top'],
    ['top', 'center'],
    ['left', 'bottom'],
    ['bottom', 'center'],
    ['left', 'center'],
  ],
};
// Optically corrected for 16–24 px, 24 grid: bigger nodes, thicker lines, wider gaps; the inner
// diagonal is dropped (at 16 px it turned the middle into noise). Same four-node silhouette.
const COMPACT = {
  size: 24,
  stroke: 1.6,
  nodes: { top: [16.2, 4.4, 3.1], left: [5.2, 9.4, 3.1], bottom: [8.2, 19.4, 3.1], center: [18.4, 15.4, 4] },
  links: [
    ['left', 'top'],
    ['top', 'center'],
    ['left', 'bottom'],
    ['bottom', 'center'],
  ],
};

const round = (value) => Math.round(value * 100) / 100;

/** The mark as SVG markup. `palette` = { node, accent, line, background? }; `inset` shrinks it into a tile. */
function mark(geometry, palette, { title, inset = 0, radius = 0 } = {}) {
  const { size, stroke, nodes, links } = geometry;
  const scale = (size - inset * 2) / size;
  const at = (value) => round(inset + value * scale);
  const parts = [];
  if (palette.background)
    parts.push(`<rect width="${size}" height="${size}" rx="${radius}" fill="${palette.background}"/>`);
  const lines = links
    .map(([from, to]) => {
      const [x1, y1] = nodes[from];
      const [x2, y2] = nodes[to];
      return `<line x1="${at(x1)}" y1="${at(y1)}" x2="${at(x2)}" y2="${at(y2)}"/>`;
    })
    .join('');
  parts.push(`<g stroke="${palette.line}" stroke-width="${round(stroke * scale)}" stroke-linecap="round">${lines}</g>`);
  for (const [name, [x, y, r]] of Object.entries(nodes))
    parts.push(
      `<circle cx="${at(x)}" cy="${at(y)}" r="${round(r * scale)}" fill="${name === 'center' ? palette.accent : palette.node}"/>`,
    );
  const label = title ? `<title>${title}</title>` : '';
  const role = title ? ' role="img" aria-label="AI Development Hub"' : ' aria-hidden="true"';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}"${role}>${label}${parts.join('')}</svg>\n`;
}

const dark = { node: COLORS.node, accent: COLORS.accent, line: COLORS.line };
const light = { node: COLORS.lightNode, accent: COLORS.lightAccent, line: COLORS.lightLine };
// Monochrome: one colour; the coordinator stays recognisable by its size.
const mono = (color) => ({ node: color, accent: color, line: color });
const files = {
  'brand/logo-nodes.svg': mark(FULL, dark, { title: 'AI Development Hub' }),
  'brand/logo-nodes-light.svg': mark(FULL, light, { title: 'AI Development Hub' }),
  'brand/logo-nodes-compact.svg': mark(COMPACT, dark, { title: 'AI Development Hub' }),
  'brand/logo-nodes-compact-light.svg': mark(COMPACT, light, { title: 'AI Development Hub' }),
  'brand/logo-nodes-monochrome.svg': mark(FULL, mono('currentColor'), { title: 'AI Development Hub' }),
  'brand/logo-nodes-monochrome-compact.svg': mark(COMPACT, mono('currentColor'), { title: 'AI Development Hub' }),
  'brand/logo-nodes-white.svg': mark(FULL, mono('#FFFFFF'), { title: 'AI Development Hub' }),
  'brand/logo-nodes-black.svg': mark(FULL, mono('#000000'), { title: 'AI Development Hub' }),
  // The browser tab: the compact mark, with a light variant for light browser chrome.
  'favicon.svg': mark(COMPACT, dark, {}).replace(
    '<g ',
    `<style>@media (prefers-color-scheme: light){circle{fill:${COLORS.lightNode}}circle:last-of-type{fill:${COLORS.lightAccent}}g{stroke:${COLORS.lightLine}}}</style><g `,
  ),
};
for (const [name, content] of Object.entries(files)) writeFileSync(`${PUBLIC}/${name}`, content);

// App icons: the mark on the dark tile, inside the maskable safe zone (inner 80 %).
const tile = (inset, radius = 0) => mark(FULL, { ...dark, background: COLORS.background }, { inset, radius });
const rasters = [
  // Raster favicons cannot follow the browser theme: the mark sits on its dark tile, legible on light tabs too.
  ['favicon-16.png', 16, mark(COMPACT, { ...dark, background: COLORS.background }, { inset: 1.2, radius: 5 })],
  ['favicon-32.png', 32, mark(COMPACT, { ...dark, background: COLORS.background }, { inset: 1.5, radius: 5 })],
  ['apple-touch-icon.png', 180, tile(10)],
  ['icons/icon-192.png', 192, tile(12)],
  ['icons/icon-512.png', 512, tile(12)],
  ['icons/icon-maskable-512.png', 512, tile(14)],
];
writeFileSync(`${PUBLIC}/icons/icon.svg`, tile(12));

const browser = await chromium.launch();
const page = await browser.newPage();
const png = {};
for (const [name, size, svg] of rasters) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
  );
  png[name] = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
  writeFileSync(`${PUBLIC}/${name}`, png[name]);
}
await browser.close();

// favicon.ico with 16 and 32 px PNG frames (PNG-in-ICO is supported by every current browser).
const frames = [
  [16, png['favicon-16.png']],
  [32, png['favicon-32.png']],
];
const header = Buffer.alloc(6 + frames.length * 16);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(frames.length, 4);
let offset = header.length;
frames.forEach(([size, data], index) => {
  const entry = 6 + index * 16;
  header.writeUInt8(size, entry);
  header.writeUInt8(size, entry + 1);
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(data.length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += data.length;
});
writeFileSync(`${PUBLIC}/favicon.ico`, Buffer.concat([header, ...frames.map(([, data]) => data)]));
console.log(`brand assets: ${Object.keys(files).length} svg, ${rasters.length} png, favicon.ico`);
