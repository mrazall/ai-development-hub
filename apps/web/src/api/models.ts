import { t } from '../i18n';

/** Claude Code does not report its models: the current family, newest first. */
export const CLAUDE_MODELS: [string, string][] = [
  ['claude-opus-5-5', 'Opus 5.5'],
  ['claude-sonnet-5-5', 'Sonnet 5.5'],
  ['claude-haiku-5-5', 'Haiku 5.5'],
];

/** Claude Code --effort levels. */
export const CLAUDE_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];

/** A model a worker's Codex offers in /model (the worker reports them from Codex's own cache). */
export type WorkerModel = { slug: string; name: string; efforts: string[]; default_effort?: string | null };

const EFFORT_LABELS: Record<string, string> = {
  minimal: 'минимальное',
  low: 'низкое',
  medium: 'среднее',
  high: 'высокое',
  xhigh: 'очень высокое',
  max: 'максимум',
  ultra: 'ультра',
};

export const effortLabel = (effort: string) => t(EFFORT_LABELS[effort] ?? effort);
