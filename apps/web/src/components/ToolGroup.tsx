import type { ReactNode } from 'react';
import { t } from '../i18n';
import { formatElapsed, GLYPHS, useNow, useReducedMotion } from './time';

/** One tool call of an agent: what the model said it does, and the call itself to expand. */
export type ToolStep = {
  key: string | number;
  /** The model's own short description of the step ("Найти упавший прогон CI"), else a label for the tool. */
  label: string;
  detail?: ReactNode;
  at?: string | null;
  failed?: boolean;
};

const LABELS: Record<string, string> = {
  Bash: 'Выполняет команду',
  Read: 'Читает файл',
  Edit: 'Меняет файл',
  Write: 'Записывает файл',
  Glob: 'Ищет файлы',
  Grep: 'Ищет в файлах',
  WebFetch: 'Открывает страницу',
  WebSearch: 'Ищет в интернете',
  Task: 'Запускает подагента',
  TodoWrite: 'Обновляет план',
};

/** A label for a tool call without the model's description. */
export function toolLabel(name?: string | null): string {
  const tool = name ?? '';
  if (tool.includes('knowledge_search')) return t('Ищет в памяти');
  if (tool.includes('knowledge_read')) return t('Читает заметку');
  if (tool.includes('orch_')) return t('Управляет исполнителями');
  if (tool.includes('knowledge')) return t('Работает с памятью');
  return LABELS[tool] ? t(LABELS[tool]) : tool || t('Инструмент');
}

/** The model's own description of a step (Claude passes one with Bash, Task…); empty when there is none. */
export function stepDescription(input: unknown): string {
  if (!input || typeof input !== 'object') return '';
  const description = (input as Record<string, unknown>).description;
  return typeof description === 'string' ? description.trim() : '';
}

const time = (value?: string | null) => (value ? new Date(value).getTime() : NaN);

/**
 * Consecutive tool calls folded into one line, like Claude Code: the current step's description, a spinner and
 * a timer while the agent works, the total time once it moved on; expand for every step.
 */
export function ToolGroup({
  steps,
  running,
  endedAt,
}: {
  steps: ToolStep[];
  running: boolean;
  endedAt?: string | null;
}): JSX.Element {
  const reduced = useReducedMotion();
  const now = useNow(running ? (reduced ? 1000 : 120) : 60_000);
  const start = time(steps[0]?.at);
  const end = running ? now : time(endedAt ?? steps.at(-1)?.at);
  const elapsed = !Number.isNaN(start) && !Number.isNaN(end) ? Math.max(0, end - start) : null;
  const current = steps.at(-1);
  const failed = steps.filter((step) => step.failed).length;
  return (
    <details className={`tool-group${running ? ' is-running' : ''}`}>
      <summary>
        <span className="tool-group-mark" aria-hidden="true">
          {running ? (reduced ? '✻' : GLYPHS[Math.floor(now / 120) % GLYPHS.length]) : '⋮'}
        </span>
        <span className="tool-group-label">{current?.label}</span>
        {steps.length > 1 && <span className="tool-group-count">· {t('шагов: {0}', steps.length)}</span>}
        {failed > 0 && <span className="tool-group-failed">· {t('ошибок: {0}', failed)}</span>}
        {elapsed !== null && elapsed >= 1000 && <span className="tool-group-time">· {formatElapsed(elapsed)}</span>}
      </summary>
      <ol className="tool-group-steps">
        {steps.map((step) => (
          <li key={step.key} className={step.failed ? 'is-failed' : undefined}>
            <span>{step.label}</span>
            {step.detail}
          </li>
        ))}
      </ol>
    </details>
  );
}
