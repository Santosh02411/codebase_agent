import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...p }, ref) => (
  <div ref={ref} className={cn("rounded-xl bg-panel shadow-card", className)} {...p} />
));
Card.displayName = "Card";

export function CardHeader({ title, description, actions, className, icon }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; className?: string; icon?: React.ReactNode }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-4 pb-0 pt-3.5", className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <div className="mt-0.5 text-muted-foreground">{icon}</div>}
        <div className="min-w-0">
          <h3 className="truncate text-[13px] font-semibold">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}
export const CardBody = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("px-4 py-3.5", className)} {...p} />;
