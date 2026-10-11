import { useId } from "react";
import { Card, CardHeader, CardContent } from "./ui/card";

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
    <Card
      className={`panel ${className ?? ""}`}
      role="region"
      aria-labelledby={id}
    >
      <CardHeader className="panel-header">
        <h2 id={id}>
          {title}
          {badge}
        </h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </CardHeader>
      <CardContent className="panel-content">{children}</CardContent>
    </Card>
  );
}
