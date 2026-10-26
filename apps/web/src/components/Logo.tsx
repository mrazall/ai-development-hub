// The Nodes mark. Geometry mirrors scripts/brand-assets.mjs (which renders the static files); keep both in sync.
// Colours come from --logo-* tokens, so the mark follows the light/dark theme.
type Geometry = {
  size: number;
  stroke: number;
  nodes: [number, number, number][]; // top, left, bottom-left, centre (the amber coordinator)
  links: [number, number][];
};

const FULL: Geometry = {
  size: 64,
  stroke: 2.5,
  nodes: [
    [43, 11, 7],
    [17, 25, 7],
    [24, 49, 7],
    [46, 39, 9],
  ],
  links: [
    [1, 0],
    [0, 3],
    [1, 2],
    [2, 3],
    [1, 3],
  ],
};
// 16–24 px: bigger nodes, thicker lines, no inner diagonal (it turned into noise at 16 px).
const COMPACT: Geometry = {
  size: 24,
  stroke: 1.6,
  nodes: [
    [16.2, 4.4, 3.1],
    [5.2, 9.4, 3.1],
    [8.2, 19.4, 3.1],
    [18.4, 15.4, 4],
  ],
  links: [
    [1, 0],
    [0, 3],
    [1, 2],
    [2, 3],
  ],
};

/**
 * Decorative by default (next to the product name); pass `title` when the mark stands alone.
 * `monochrome` paints everything in currentColor.
 */
export function LogoMark({
  size = 24,
  title,
  monochrome = false,
  className = '',
}: {
  size?: number;
  title?: string;
  monochrome?: boolean;
  className?: string;
}): JSX.Element {
  const geometry = size <= 24 ? COMPACT : FULL;
  const node = monochrome ? 'currentColor' : 'var(--logo-node)';
  const accent = monochrome ? 'currentColor' : 'var(--logo-accent)';
  const line = monochrome ? 'currentColor' : 'var(--logo-line)';
  return (
    <svg
      className={`logo-mark ${className}`}
      width={size}
      height={size}
      viewBox={`0 0 ${geometry.size} ${geometry.size}`}
      {...(title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': true, focusable: false })}
    >
      {title && <title>{title}</title>}
      <g stroke={line} strokeWidth={geometry.stroke} strokeLinecap="round">
        {geometry.links.map(([from, to]) => (
          <line
            key={`${from}-${to}`}
            x1={geometry.nodes[from][0]}
            y1={geometry.nodes[from][1]}
            x2={geometry.nodes[to][0]}
            y2={geometry.nodes[to][1]}
          />
        ))}
      </g>
      {geometry.nodes.map(([x, y, r], index) => (
        <circle key={index} cx={x} cy={y} r={r} fill={index === 3 ? accent : node} />
      ))}
    </svg>
  );
}

/** [mark] AI Development Hub — the text hides on narrow screens, the mark stays. */
export function LogoLockup({ size = 28 }: { size?: number }): JSX.Element {
  return (
    <span className="logo-lockup">
      <LogoMark size={size} />
      <span className="logo-lockup-text">AI Development Hub</span>
    </span>
  );
}
