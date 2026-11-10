import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("relative overflow-hidden rounded-md bg-muted", "after:absolute after:inset-0 after:-translate-x-full after:animate-[shimmer_1.4s_infinite] after:bg-gradient-to-r after:from-transparent after:via-foreground/5 after:to-transparent", className)} />;
}
export const SkeletonRows = ({ n = 5, className }: { n?: number; className?: string }) => (
  <div className={cn("space-y-2", className)} role="status" aria-label="Loading">{Array.from({ length: n }, (_, i) => <Skeleton key={i} className="h-8" />)}</div>
);
