import { type RefObject, useEffect, useState } from 'react';
import { Icon } from './ui/icons';
import { t } from '../i18n';

export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Older browsers or a non-secure origin: fall back to a hidden textarea.
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
}

/** A small button that copies `text` and says so for a moment. */
export function CopyButton({
  text,
  label = t('Копировать'),
  className = '',
}: {
  text: string | (() => string);
  label?: string;
  className?: string;
}): JSX.Element {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return undefined;
    const timer = window.setTimeout(() => setDone(false), 1500);
    return () => window.clearTimeout(timer);
  }, [done]);
  return (
    <button
      type="button"
      className={`copy-button ${done ? 'copied' : ''} ${className}`}
      aria-label={done ? t('Скопировано') : label}
      title={done ? t('Скопировано') : label}
      onClick={() => {
        void copyText(typeof text === 'function' ? text() : text).then(() => setDone(true));
      }}
    >
      <Icon name={done ? 'check' : 'copy'} size={16} />
    </button>
  );
}

/** Fired with the selected text; the chat composers turn it into a quote. */
export const quoteEvent = 'aihub:quote';

export function quoteMarkdown(text: string): string {
  return `${text
    .trim()
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join('\n')}\n\n`;
}

/**
 * Shows «Ответить» next to a text selection inside `container`; clicking it sends the selection as a
 * quote to the chat composer of this page.
 */
export function QuoteSelection({ container }: { container: RefObject<HTMLElement> }): JSX.Element | null {
  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null);
  useEffect(() => {
    const update = () => {
      const current = window.getSelection();
      const text = current?.toString().trim() ?? '';
      const root = container.current;
      if (!current || !text || !root || current.rangeCount === 0 || !root.contains(current.anchorNode)) {
        setSelection(null);
        return;
      }
      const rect = current.getRangeAt(0).getBoundingClientRect();
      setSelection({ text, x: rect.left + rect.width / 2, y: rect.top });
    };
    document.addEventListener('selectionchange', update);
    return () => document.removeEventListener('selectionchange', update);
  }, [container]);
  if (!selection) return null;
  return (
    <button
      type="button"
      className="quote-selection"
      style={{ left: selection.x, top: selection.y }}
      // Keep the selection: a mousedown on a button would clear it before the click.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => {
        window.dispatchEvent(new CustomEvent(quoteEvent, { detail: quoteMarkdown(selection.text) }));
        window.getSelection()?.removeAllRanges();
        setSelection(null);
      }}
    >
      <Icon name="reply" size={15} />
      {t('Ответить')}
    </button>
  );
}
