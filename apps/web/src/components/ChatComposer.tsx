import { useEffect, useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { Attachment } from '../api/types-ops';
import './ops.css';
import { quoteEvent } from './copy';
import { Icon } from './ui/icons';
import { t } from '../i18n';

const MAX_BYTES = 20 * 1024 * 1024;
const formatSize = (size: number) => t('{0} МБ', (size / 1024 / 1024).toFixed(size > 1024 * 1024 ? 1 : 2));
const imageDataUrl = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('preview failed'));
    reader.readAsDataURL(file);
  });

type ComposerProps = {
  sessionId: string;
  /** A finished Claude session is woken up through "continue" instead of an event nobody reads. */
  resumable?: boolean;
  onContinued?: (sessionId: string) => void;
  /** Claude Code permissions of the session; set → the composer offers to change them for the continuation. */
  permissionMode?: string;
};

export function ChatComposer({
  sessionId,
  resumable = false,
  onContinued,
  permissionMode,
}: ComposerProps): JSX.Element {
  const [text, setText] = useState('');
  const [mode, setMode] = useState(permissionMode ?? 'edits');
  useEffect(() => setMode(permissionMode ?? 'edits'), [permissionMode, sessionId]);
  useEffect(() => {
    // «Ответить» on a selected phrase in the feed: quote it at the top of the message.
    const onQuote = (event: Event) => setText((current) => `${(event as CustomEvent<string>).detail}${current}`);
    window.addEventListener(quoteEvent, onQuote);
    return () => window.removeEventListener(quoteEvent, onQuote);
  }, []);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const input = useRef<HTMLInputElement>(null);
  const addFiles = async (selected: FileList | File[]) => {
    setError('');
    const list = Array.from(selected);
    if (files.length + list.length > 10) return setError(t('Можно прикрепить не больше 10 файлов.'));
    for (const file of list) {
      if (file.size > MAX_BYTES) return setError(t('{0}: файл больше 20 МБ.', file.name));
      try {
        const data = new FormData();
        data.append('file', file);
        const attachment = await api<Attachment>(`/sessions/${sessionId}/attachments`, { method: 'POST', body: data });
        setFiles((current) => [...current, attachment]);
        if (file.type.startsWith('image/')) {
          void imageDataUrl(file)
            .then((preview) => setPreviews((current) => ({ ...current, [attachment.id]: preview })))
            .catch(() => undefined);
        }
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : t('{0}: тип файла не поддерживается.', file.name));
        return;
      }
    }
  };
  const remove = async (attachment: Attachment) => {
    try {
      await api(`/attachments/${attachment.id}`, { method: 'DELETE' });
      setFiles((current) => current.filter((item) => item.id !== attachment.id));
      setPreviews((current) => {
        const next = { ...current };
        delete next[attachment.id];
        return next;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Не удалось удалить файл'));
    }
  };
  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim() && files.length === 0) return;
    setBusy(true);
    setError('');
    try {
      const attachmentIds = files.map((item) => item.id);
      if (resumable) {
        const next = await api<{ id: string }>(`/sessions/${sessionId}/continue`, {
          method: 'POST',
          body: JSON.stringify({
            text: text.trim(),
            attachment_ids: attachmentIds,
            ...(permissionMode ? { permission_mode: mode } : {}),
          }),
        });
        onContinued?.(next.id);
      } else {
        // The endpoint takes a batch of events.
        await api(`/sessions/${sessionId}/events`, {
          method: 'POST',
          body: JSON.stringify([
            { kind: 'message', payload: { role: 'user', text: text.trim(), attachment_ids: attachmentIds } },
          ]),
        });
      }
      setText('');
      setFiles([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Сообщение не отправлено'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="chat-form"
      onSubmit={send}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        void addFiles(event.dataTransfer.files);
      }}
    >
      {files.length > 0 && (
        <div className="attachment-chips" aria-label={t('Прикреплённые файлы')}>
          {files.map((file) => (
            <span className="attachment-chip" key={file.id}>
              {previews[file.id] ? (
                <img className="attachment-preview" src={previews[file.id]} alt="" />
              ) : (
                <Icon name={file.mime_type.startsWith('image/') ? 'image' : 'file'} size={15} />
              )}{' '}
              {file.original_name} <small>{formatSize(file.size_bytes)}</small>
              <button type="button" aria-label={t('Удалить {0}', file.original_name)} onClick={() => void remove(file)}>
                <Icon name="close" size={14} />
              </button>
            </span>
          ))}
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <input
        aria-label={t('Сообщение агенту')}
        placeholder={t('Написать агенту… Файл: перетащите или вставьте (Ctrl+V)')}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onPaste={(event) => {
          // Screenshots and files copied in a file manager arrive as clipboard files; plain text pastes as usual.
          const pasted = Array.from(event.clipboardData.files);
          if (pasted.length) {
            event.preventDefault();
            void addFiles(pasted);
          }
        }}
      />
      <button
        type="button"
        className="button-secondary"
        aria-label={t('Прикрепить файл')}
        onClick={() => input.current?.click()}
      >
        <Icon name="attach" />
      </button>
      <input
        ref={input}
        hidden
        type="file"
        multiple
        onChange={(event) => {
          if (event.target.files) void addFiles(event.target.files);
          event.currentTarget.value = '';
        }}
      />
      {resumable && permissionMode && (
        <select
          className="composer-permissions"
          aria-label={t('Права агента')}
          title={t('Права агента для продолжения')}
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          <option value="edits">{t('Только правки')}</option>
          <option value="ask">{t('Спрашивать')}</option>
          <option value="auto">{t('Авто')}</option>
          <option value="all">{t('Разрешить всё')}</option>
        </select>
      )}
      <button disabled={busy || (!text.trim() && files.length === 0)}>{busy ? t('Отправка…') : t('Отправить')}</button>
    </form>
  );
}
