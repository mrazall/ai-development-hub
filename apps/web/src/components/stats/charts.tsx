import { useEffect, useRef, useState } from 'react';
import { t } from '../../i18n';

// Shared pieces of the statistics page: number formats and the stacked daily chart with its legend.
export const tokens = (value: number) =>
  value >= 1e9
    ? `${(value / 1e9).toFixed(1)} B`
    : value >= 1e6
      ? `${(value / 1e6).toFixed(1)} M`
      : value >= 1e3
        ? `${(value / 1e3).toFixed(1)} k`
        : String(value);
export const money = (value: number) => `$${value >= 100 ? value.toFixed(0) : value.toFixed(2)}`;
export const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' });

export function days(from: string, to: string): string[] {
  const out: string[] = [];
  for (
    let day = new Date(`${from}T00:00:00Z`);
    day <= new Date(`${to}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + 1)
  )
    out.push(day.toISOString().slice(0, 10));
  return out;
}

export type Series = { key: string; label: string; slot: number };
export type Column = { date: string; values: Record<string, number>; total: number };

/** Stacked columns per day, one categorical slot per model; hover shows the day's breakdown. */
export function DailyChart({
  title,
  columns,
  series,
  format,
}: {
  title: string;
  columns: Column[];
  series: Series[];
  format: (value: number) => string;
}): JSX.Element {
  const [hover, setHover] = useState<number | null>(null);
  // Drawn in the frame's own pixels: the page is one screen tall, so the chart takes the height it is given.
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 720, height: 220 });
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ width: Math.round(width), height: Math.round(height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const { width, height } = size;
  const pad = { top: 12, right: 8, bottom: 26, left: 52 };
  const max = Math.max(...columns.map((column) => column.total), 0) || 1;
  const step = (width - pad.left - pad.right) / Math.max(columns.length, 1);
  const bar = Math.max(2, Math.min(28, step - 2));
  const y = (value: number) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  const ticks = [0, 0.5, 1].map((share) => share * max);
  const labelEvery = Math.ceil(columns.length / Math.max(2, Math.floor(width / 90)));
  const shown = hover === null ? null : columns[hover];
  return (
    <section className="panel stats-chart">
      <div className="panel-heading">
        <h2>{title}</h2>
      </div>
      <div className="stats-chart-frame" ref={frame}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
          {ticks.map((tick) => (
            <g key={tick} className="stats-grid-line">
              <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} />
              <text x={pad.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {format(tick)}
              </text>
            </g>
          ))}
          {columns.map((column, index) => {
            const x = pad.left + index * step + (step - bar) / 2;
            let base = 0;
            return (
              <g key={column.date}>
                {series.map((item) => {
                  const value = column.values[item.key] ?? 0;
                  if (!value) return null;
                  const top = y(base + value);
                  const bottom = y(base);
                  base += value;
                  // 2px surface gap between stacked segments; the top segment gets the rounded end.
                  return (
                    <rect
                      key={item.key}
                      className={`stats-series-${item.slot}`}
                      x={x}
                      y={top}
                      width={bar}
                      height={Math.max(bottom - top - 2, 1)}
                      rx={base >= column.total ? Math.min(4, bar / 2) : 0}
                      opacity={hover === null || hover === index ? 1 : 0.45}
                    />
                  );
                })}
                {index % labelEvery === 0 && (
                  <text className="stats-axis-label" x={x + bar / 2} y={height - 8} textAnchor="middle">
                    {dayLabel(column.date)}
                  </text>
                )}
                <rect
                  className="stats-hit"
                  x={pad.left + index * step}
                  y={pad.top}
                  width={step}
                  height={height - pad.top - pad.bottom}
                  onMouseEnter={() => setHover(index)}
                />
              </g>
            );
          })}
        </svg>
        {shown && (
          <div
            className="stats-tooltip"
            style={{ left: `${Math.min(80, Math.max(20, ((pad.left + (hover! + 0.5) * step) / width) * 100))}%` }}
            role="status"
          >
            <strong>{dayLabel(shown.date)}</strong>
            {series
              .filter((item) => shown.values[item.key])
              .map((item) => (
                <span key={item.key}>
                  <i className={`stats-swatch stats-series-${item.slot}`} />
                  {item.label}
                  <b>{format(shown.values[item.key])}</b>
                </span>
              ))}
            <span className="stats-tooltip-total">
              {t('Всего')}
              <b>{format(shown.total)}</b>
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

export function Legend({ series }: { series: Series[] }): JSX.Element {
  return (
    <div className="stats-legend" aria-label={t('Модели')}>
      {series.map((item) => (
        <span key={item.key}>
          <i className={`stats-swatch stats-series-${item.slot}`} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
