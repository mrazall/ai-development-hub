import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type DialogHTMLAttributes,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { Icon } from './icons';
import { lang, setLang, t, type Lang } from '../../i18n';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export function Button({
  variant = 'primary',
  loading = false,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }): JSX.Element {
  return (
    <button
      className={`ui-button ui-button-${variant}`}
      aria-busy={loading || undefined}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? t('Загрузка…') : children}
    </button>
  );
}
export function IconButton({
  label,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }): JSX.Element {
  return (
    <button className="ui-icon-button" aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <label className="ui-field">
      <span>{label}</span>
      {children}
      {error ? <small className="ui-field-error">{error}</small> : hint ? <small>{hint}</small> : null}
    </label>
  );
}
export function Input(props: InputHTMLAttributes<HTMLInputElement>): JSX.Element {
  return <input className="ui-input" {...props} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>): JSX.Element {
  return <select className="ui-input" {...props} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>): JSX.Element {
  return <textarea className="ui-input" {...props} />;
}
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }): JSX.Element {
  return <section className={`ui-panel ${className}`}>{children}</section>;
}
export function Toolbar({ children }: { children: ReactNode }): JSX.Element {
  return <div className="ui-toolbar">{children}</div>;
}
export function Tabs({
  items,
  value,
  onChange,
}: {
  items: { id: string; label: string }[];
  value: string;
  onChange: (id: string) => void;
}): JSX.Element {
  return (
    <div className="ui-tabs" role="tablist">
      {items.map((item) => (
        <button
          key={item.id}
          role="tab"
          aria-selected={value === item.id}
          className={value === item.id ? 'active' : ''}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'success' | 'danger' | 'warning';
}): JSX.Element {
  return <span className={`ui-badge ui-badge-${tone}`}>{children}</span>;
}
export function Skeleton({ width = '100%', height = '1rem' }: { width?: string; height?: string }): JSX.Element {
  return <span className="ui-skeleton" style={{ width, height }} aria-hidden="true" />;
}
export function EmptyState({
  title = t('Здесь пока пусто'),
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children?: ReactNode;
}): JSX.Element {
  return (
    <div className="ui-empty">
      <div className="ui-empty-icon" aria-hidden="true">
        <Icon name="spark" size={22} />
      </div>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }): JSX.Element {
  return (
    <div className="ui-error" role="alert">
      <strong>{t('Не удалось загрузить данные')}</strong>
      <p>{message}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {t('Повторить')}
        </Button>
      )}
    </div>
  );
}
/** Compatibility names keep page code declarative while routing all states through the design system. */
export function Loading(): JSX.Element {
  return (
    <div className="ui-loading" role="status" aria-label={t('Загрузка')}>
      <Skeleton width="12rem" height="1rem" />
      <Skeleton width="75%" height="0.8rem" />
    </div>
  );
}
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }): JSX.Element {
  return <ErrorState message={message} onRetry={onRetry} />;
}
export const STATUS_LABELS: Record<string, string> = {
  online: t('в сети'),
  offline: t('не в сети'),
  draining: t('выводится'),
  running: t('в работе'),
  queued: t('в очереди'),
  starting: t('запускается'),
  waiting_approval: t('ждёт подтверждения'),
  blocked: t('заблокировано'),
  failed: t('ошибка'),
  completed: t('завершено'),
  pending: t('ожидает'),
  approved: t('разрешено'),
  rejected: t('отклонено'),
  expired: t('истекло'),
  info: t('информация'),
  warning: t('предупреждение'),
  critical: t('критично'),
  admin: t('администратор'),
  viewer: t('только чтение'),
  private: t('личный'),
  shared: t('общий'),
  public: t('публичный'),
  unknown: t('неизвестно'),
  draft: t('черновик'),
  ready: t('готово к запуску'),
  idle: t('ничего не запущено'),
};

export type StatusTone = 'working' | 'success' | 'danger' | 'warning' | 'neutral';

/** One mapping for the whole site: work in progress is green and pulses, errors are red, done is a check. */
export function statusTone(value: string): StatusTone {
  if (['running', 'starting', 'queued'].includes(value)) return 'working';
  if (['online', 'ok', 'completed', 'approved', 'public', 'shared'].includes(value)) return 'success';
  if (['failed', 'offline', 'rejected', 'critical', 'blocked', 'error'].includes(value)) return 'danger';
  if (['warning', 'waiting_approval', 'pending', 'draining'].includes(value)) return 'warning';
  return 'neutral';
}

const statusLabel = (value: string) => STATUS_LABELS[value] ?? value.replaceAll('_', ' ');

function StatusGlyph({ tone }: { tone: StatusTone }): JSX.Element {
  if (tone === 'success') return <Icon name="check" size={14} strokeWidth={2.4} />;
  if (tone === 'danger') return <Icon name="alert" size={14} strokeWidth={2.2} />;
  if (tone === 'warning') return <Icon name="warning" size={14} strokeWidth={2.2} />;
  return <span className="status-dot" />;
}

export function StatusBadge({ value: raw }: { value: string | null | undefined }): JSX.Element {
  const value = raw || 'unknown';
  const tone = statusTone(value);
  return (
    <span className={`status-badge status-badge-${tone}`}>
      <span className="status-glyph" aria-hidden="true">
        <StatusGlyph tone={tone} />
      </span>
      {statusLabel(value)}
    </span>
  );
}

/** The same status as an icon only (dense lists); the label is in the tooltip and for screen readers. */
export function StatusIcon({ value: raw, label }: { value: string | null | undefined; label?: string }): JSX.Element {
  const value = raw || 'unknown';
  const tone = statusTone(value);
  const text = label ?? statusLabel(value);
  return (
    <span className={`status-icon status-badge-${tone}`} role="img" aria-label={text} title={text}>
      <StatusGlyph tone={tone} />
    </span>
  );
}

/** What the icons in a list mean. */
export function StatusLegend({
  items = [
    ['running', t('в работе')],
    ['failed', t('ошибка')],
    ['completed', t('готово')],
    ['draft', t('ожидает')],
  ],
}: {
  items?: [string, string][];
}): JSX.Element {
  return (
    <ul className="status-legend" aria-label={t('Обозначения статусов')}>
      {items.map(([value, text]) => (
        <li key={value}>
          <span className={`status-icon status-badge-${statusTone(value)}`} aria-hidden="true">
            <StatusGlyph tone={statusTone(value)} />
          </span>
          {text}
        </li>
      ))}
    </ul>
  );
}
export function Dialog({
  open,
  title,
  onClose,
  children,
  ...props
}: DialogHTMLAttributes<HTMLDialogElement> & {
  open: boolean;
  title: string;
  onClose: () => void;
}): JSX.Element | null {
  const ref = useRef<HTMLDialogElement>(null);
  const previous = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      previous.current = document.activeElement as HTMLElement;
      dialog.showModal();
    } else if (dialog.open) dialog.close();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, [open]);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const esc = () => onClose();
    dialog.addEventListener('cancel', esc);
    return () => {
      dialog.removeEventListener('cancel', esc);
      if (previous.current) previous.current.focus();
    };
  }, [onClose]);
  if (!open) return null;
  return (
    <dialog
      ref={ref}
      className="ui-dialog"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      {...props}
    >
      <div className="ui-dialog-content">
        <div className="ui-dialog-heading">
          <h2>{title}</h2>
          <IconButton label={t('Закрыть')} onClick={onClose}>
            <Icon name="close" />
          </IconButton>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function ConfirmDialog({
  open,
  title = t('Подтвердите действие'),
  name,
  description,
  confirmLabel = t('Подтвердить'),
  danger = Boolean(name),
  onConfirm,
  onClose,
}: {
  open: boolean;
  title?: string;
  /** Only for irreversible actions: the user must type this exact name to confirm. */
  name?: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}): JSX.Element | null {
  const [value, setValue] = useState('');
  return (
    <Dialog open={open} title={title} onClose={onClose}>
      {description && <p>{description}</p>}
      {name && (
        <>
          <p>
            {t('Для подтверждения введите «')}
            {name}».
          </p>
          <Input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            autoFocus
            aria-label={t('Название для подтверждения')}
          />
        </>
      )}
      <div className="ui-dialog-actions">
        <Button variant="secondary" onClick={onClose}>
          {t('Отмена')}
        </Button>
        <Button
          variant={danger ? 'danger' : 'primary'}
          disabled={Boolean(name) && value !== name}
          onClick={onConfirm}
          autoFocus={!name}
        >
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}
export function Toast({
  message,
  tone = 'success',
  onClose,
}: {
  message: string;
  tone?: 'success' | 'error';
  onClose?: () => void;
}): JSX.Element {
  return (
    <div className={`ui-toast ui-toast-${tone}`} role="status" aria-live="polite">
      {message}
      {onClose && (
        <IconButton label={t('Закрыть уведомление')} onClick={onClose}>
          <Icon name="close" />
        </IconButton>
      )}
    </div>
  );
}
export function Table({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="ui-table-wrap">
      <table className="ui-table">{children}</table>
    </div>
  );
}
export function Sidebar({ children, collapsed = false }: { children: ReactNode; collapsed?: boolean }): JSX.Element {
  return <aside className={`ui-sidebar ${collapsed ? 'collapsed' : ''}`}>{children}</aside>;
}
export function SplitPane({
  children,
  initial = 320,
  min = 220,
  max = 520,
  storageKey = 'aihub.split-pane',
  className = '',
  mobileTab,
  collapsible = false,
  collapsedLabel = t('Панель'),
}: {
  children: ReactNode[];
  initial?: number;
  min?: number;
  max?: number;
  storageKey?: string;
  className?: string;
  mobileTab?: string;
  /** The first pane can be folded to a thin strip (remembered per storageKey). */
  collapsible?: boolean;
  collapsedLabel?: string;
}): JSX.Element {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return collapsible && localStorage.getItem(`${storageKey}.collapsed`) === '1';
    } catch {
      return false;
    }
  });
  // On a phone the panes are tabs (mobileTab): folding makes no sense there.
  const folded = collapsed && window.matchMedia('(min-width: 901px)').matches;
  const toggle = () =>
    setCollapsed((value) => {
      try {
        localStorage.setItem(`${storageKey}.collapsed`, value ? '0' : '1');
      } catch {
        /* storage is optional */
      }
      return !value;
    });
  const [size, setSize] = useState(() => {
    try {
      // A missing key is null → Number(null) === 0, which clamped every pane to its minimum width.
      const raw = localStorage.getItem(storageKey);
      const saved = raw === null ? NaN : Number(raw);
      return Number.isFinite(saved) && saved > 0 ? Math.min(max, Math.max(min, saved)) : initial;
    } catch {
      return initial;
    }
  });
  const save = (next: number) => {
    const value = Math.min(max, Math.max(min, next));
    setSize(value);
    try {
      localStorage.setItem(storageKey, String(value));
    } catch {
      /* storage is optional */
    }
  };
  const start = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const x = event.clientX;
    const origin = size;
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (moveEvent: PointerEvent) => save(origin + moveEvent.clientX - x);
    const end = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
  };
  const keyboard = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      event.preventDefault();
      save(size - 16);
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      event.preventDefault();
      save(size + 16);
    } else if (event.key === 'Home') {
      event.preventDefault();
      save(min);
    } else if (event.key === 'End') {
      event.preventDefault();
      save(max);
    }
  };
  return (
    <div
      className={`ui-split ui-split-${children.length} ${className} ${folded ? 'ui-split-collapsed' : ''}`}
      data-mobile-tab={mobileTab}
      style={{ '--split-size': folded ? '2.5rem' : `${size}px` } as CSSProperties}
    >
      {children.length === 2 ? (
        <>
          <div className="ui-split-pane">
            {folded ? (
              <button
                className="ui-split-expand"
                onClick={toggle}
                aria-label={t('Развернуть: {0}', collapsedLabel)}
                title={t('Развернуть: {0}', collapsedLabel)}
              >
                <Icon name="expand" />
                <span className="ui-split-expand-label">{collapsedLabel}</span>
              </button>
            ) : (
              <>
                {collapsible && (
                  <button
                    className="ui-split-collapse"
                    onClick={toggle}
                    aria-label={t('Свернуть: {0}', collapsedLabel)}
                    title={t('Свернуть: {0}', collapsedLabel)}
                  >
                    <Icon name="collapse" />
                  </button>
                )}
                {children[0]}
              </>
            )}
          </div>
          <button
            className="ui-split-handle"
            aria-label={t('Изменить размер панели')}
            onPointerDown={start}
            onKeyDown={keyboard}
            onDoubleClick={() => save(initial)}
            disabled={folded}
          />
          <div className="ui-split-pane">{children[1]}</div>
        </>
      ) : (
        children.map((child, index) => (
          <div className="ui-split-pane" key={index}>
            {child}
            {index < children.length - 1 && (
              <button
                className="ui-split-handle"
                aria-label={t('Изменить размер панели')}
                onPointerDown={start}
                onKeyDown={keyboard}
                onDoubleClick={() => save(initial)}
              />
            )}
          </div>
        ))
      )}
    </div>
  );
}
export function LangToggle(): JSX.Element {
  return (
    <label className="theme-control">
      <select value={lang} onChange={(event) => setLang(event.target.value as Lang)} aria-label="Language / Язык">
        <option value="en">EN</option>
        <option value="ru">RU</option>
      </select>
    </label>
  );
}

export function ThemeToggle(): JSX.Element {
  const [theme, setTheme] = useState(() => localStorage.getItem('aihub.theme') ?? 'dark');
  useEffect(() => {
    // Monochrome Signal is dark by default; "system" follows the OS preference.
    const resolved =
      theme === 'system' ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : theme;
    document.documentElement.dataset.theme = resolved;
    try {
      localStorage.setItem('aihub.theme', theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return (
    <label className="theme-control">
      <span>{t('Тема')}</span>
      <select value={theme} onChange={(event) => setTheme(event.target.value)} aria-label={t('Тема интерфейса')}>
        <option value="system">{t('Системная')}</option>
        <option value="light">{t('Светлая')}</option>
        <option value="dark">{t('Тёмная')}</option>
      </select>
    </label>
  );
}
