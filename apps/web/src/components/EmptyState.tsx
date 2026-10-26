export function EmptyState({
  children,
  title,
  action,
}: {
  children?: React.ReactNode;
  title?: string;
  action?: React.ReactNode;
}): JSX.Element {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        ○
      </span>
      {title && <h2>{title}</h2>}
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
