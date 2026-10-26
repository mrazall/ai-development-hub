import { type ReactNode, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CopyButton } from './copy';

const WIKI_PREFIX = '#wiki/';
const WIKI_LINK = /!?\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]+))?\]\]/g;
const CALLOUT = /^(\s*>\s*)\[!(\w+)\][+-]?\s*(.*)$/gm;

/** Obsidian syntax → plain Markdown: wiki links become in-app links, callout markers become a bold title. */
export function prepareObsidianMarkdown(text: string): string {
  return text
    .replace(WIKI_LINK, (_match, target: string, heading: string | undefined, alias: string | undefined) => {
      const label = (alias ?? `${target}${heading ?? ''}`).trim();
      return `[${label.replace(/[[\]]/g, '')}](${WIKI_PREFIX}${encodeURIComponent(target.trim())})`;
    })
    .replace(CALLOUT, (_match, quote: string, kind: string, title: string) => `${quote}**${title.trim() || kind}**`);
}

type Props = { content: string; onWikiLink?: (target: string) => void };

/** Code and commands get their own copy button, like in the Claude app. */
function CodeBlock({ children }: { children?: ReactNode }): JSX.Element {
  const ref = useRef<HTMLPreElement>(null);
  const [tall, setTall] = useState(false);
  useLayoutEffect(() => {
    setTall((ref.current?.innerText.replace(/\n$/, '').split('\n').length ?? 0) > 2);
  });
  return (
    <div className={`code-block ${tall ? 'code-block-tall' : ''}`}>
      <CopyButton className="code-copy" text={() => ref.current?.innerText.replace(/\n$/, '') ?? ''} />
      <pre ref={ref}>{children}</pre>
    </div>
  );
}

export function MarkdownView({ content, onWikiLink }: Props): JSX.Element {
  const prepared = useMemo(() => prepareObsidianMarkdown(content), [content]);
  return (
    <div className="markdown-body">
      {/* Raw HTML in notes is not rendered (react-markdown default): notes are data, not markup we trust. */}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          a: ({ href = '', children }) =>
            href.startsWith(WIKI_PREFIX) ? (
              <a
                href={href}
                className="wiki-link"
                onClick={(event) => {
                  event.preventDefault();
                  onWikiLink?.(decodeURIComponent(href.slice(WIKI_PREFIX.length)));
                }}
              >
                {children}
              </a>
            ) : (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            ),
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
