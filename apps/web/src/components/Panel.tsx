import { useId } from "react";

export function Panel({
  title,
  badge,
  actions,
  children,
  className,
}: {
  title: string;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section className={`panel ${className ?? ""}`} aria-labelledby={id}>
      <div className="panel-header">
        <h2 id={id}>
          {title}
          {badge}
        </h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
