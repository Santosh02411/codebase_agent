export function Logo({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden fill="none">
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path d="M11 11.5 6.5 16l4.5 4.5M21 11.5l4.5 4.5-4.5 4.5" stroke="hsl(var(--primary-foreground))" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="16" r="2.3" fill="hsl(var(--primary-foreground))" />
    </svg>
  );
}
