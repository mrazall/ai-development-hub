import { tokenKey } from '../api/client';
import type { Attachment } from '../api/types-ops';
import { useApi } from '../api/useApi';
import { Icon } from './ui/icons';
import { t } from '../i18n';

/** Files attached to a session (refetched on any write, e.g. a new upload). */
export function useSessionAttachments(sessionId: string): Attachment[] {
  return useSessionAttachmentList(sessionId).items;
}

/** The same with a `loaded` flag, for views that must not render before the names are known. */
export function useSessionAttachmentList(sessionId: string): { items: Attachment[]; loaded: boolean } {
  const list = useApi<Attachment[]>(`/sessions/${encodeURIComponent(sessionId)}/attachments`);
  return { items: list.data ?? [], loaded: list.data !== null || Boolean(list.error) };
}

const size = (bytes: number) =>
  bytes >= 1024 * 1024
    ? t('{0} МБ', (bytes / 1024 / 1024).toFixed(1))
    : t('{0} КБ', Math.max(1, Math.round(bytes / 1024)));

// The download needs the bearer token, so a plain link would not do: fetch and save the blob.
async function download(item: Attachment): Promise<void> {
  const response = await fetch(`/api/v0/attachments/${encodeURIComponent(item.id)}`, {
    headers: { Authorization: `Bearer ${sessionStorage.getItem(tokenKey) ?? ''}` },
  });
  if (!response.ok) return;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = item.original_name;
  link.click();
  URL.revokeObjectURL(url);
}

/** File chips; with `ids` only those files (the ones a message refers to). */
export function AttachmentChips({ items, ids }: { items: Attachment[]; ids?: unknown }): JSX.Element | null {
  const wanted = Array.isArray(ids) ? new Set(ids.map(String)) : null;
  const shown = wanted ? items.filter((item) => wanted.has(item.id)) : items;
  const missing = wanted ? wanted.size - shown.length : 0;
  if (!shown.length && !missing) return null;
  return (
    <span className="attachment-list">
      {shown.map((item) => (
        <button
          key={item.id}
          type="button"
          className="attachment-chip"
          title={t('Скачать {0}', item.original_name)}
          onClick={() => void download(item)}
        >
          <Icon name={item.mime_type.startsWith('image/') ? 'image' : 'file'} size={14} />
          {item.original_name}
          <small>{size(item.size_bytes)}</small>
        </button>
      ))}
      {missing > 0 && (
        <span className="muted">
          +{missing} {t('файл(а)')}
        </span>
      )}
    </span>
  );
}
