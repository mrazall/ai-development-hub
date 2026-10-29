import { useState } from 'react';
import { api } from '../api/client';
import type { Session } from '../api/types';
import { t } from '../i18n';

/** «Всё ок» for a failed session: the owner has seen it, the panel stops showing it as a problem. */
export function AcknowledgeButton({ session }: { session: Session }): JSX.Element {
  const [busy, setBusy] = useState(false);
  const done = Boolean(session.acknowledged_at);
  const toggle = async () => {
    setBusy(true);
    try {
      await api(`/sessions/${encodeURIComponent(session.id)}/acknowledge`, { method: done ? 'DELETE' : 'POST' });
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      className="button-secondary"
      onClick={() => void toggle()}
      disabled={busy}
      title={done ? t('Снова показывать как ошибку') : t('Отметить: ошибку видел, всё в порядке')}
    >
      {done ? t('Вернуть как ошибку') : t('Всё ок')}
    </button>
  );
}
