import { cn } from '@/lib/utils'

type StatusVariant = 'connected' | 'error' | 'warning' | 'inactive' | 'info'

const VARIANT_CLASSES: Record<StatusVariant, string> = {
  connected:
    'bg-emerald-50 text-emerald-700 ring-emerald-200/80 dark:bg-emerald-900/30 dark:text-emerald-300 dark:ring-emerald-800/60',
  error:
    'bg-red-50 text-red-700 ring-red-200/80 dark:bg-red-900/30 dark:text-red-300 dark:ring-red-800/60',
  warning:
    'bg-amber-50 text-amber-800 ring-amber-200/80 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800/60',
  inactive:
    'bg-muted text-muted-foreground ring-border',
  info:
    'bg-primary/10 text-primary ring-primary/20 dark:bg-primary/15 dark:text-primary',
}

interface StatusBadgeProps {
  variant: StatusVariant
  label: string
  className?: string
}

export function StatusBadge({ variant, label, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] ring-1',
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current shrink-0" />
      {label}
    </span>
  )
}
