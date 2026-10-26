import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { Session } from '../api/types';
import { ConfirmDialog } from './ui';
import { t } from '../i18n';

// Matches the server: only sessions no agent is working on may be deleted.
const finished = new Set(['completed', 'failed', 'offline']);

export function DeleteSessionButton({
  session,
  onDeleted,
}: {
  session: Session;
  onDeleted: () => void;
}): JSX.Element | null {
  const [open, setOpen] = useState(false);
  if (!finished.has(session.status)) return null;
  const remove = async (): Promise<void> => {
    setOpen(false);
    try {
      await api(`/sessions/${encodeURIComponent(session.id)}`, { method: 'DELETE' });
      onDeleted();
    } catch (error) {
      window.alert(error instanceof ApiError ? error.message : t('Не удалось удалить сессию'));
    }
  };
  return (
    <>
      <button
        type="button"
        className="icon-delete"
        title={t('Удалить сессию')}
        aria-label={t('Удалить сессию')}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
      >
        <svg
          viewBox="0 0 24 24"
          width="15"
          height="15"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" />
        </svg>
      </button>
      <ConfirmDialog
        open={open}
        title={t('Удалить сессию?')}
        description={t(
          '«{0}» и её журнал будут удалены{1}. Файлы в рабочей папке останутся.',
          session.title || session.engine,
          session.role === 'orchestrator' ? ' вместе с исполнителями' : '',
        )}
        confirmLabel={t('Удалить')}
        danger
        onClose={() => setOpen(false)}
        onConfirm={() => void remove()}
      />
    </>
  );
}
