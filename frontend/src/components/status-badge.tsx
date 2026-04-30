import { cn } from '@/lib/utils'

type StatusVariant = 'connected' | 'error' | 'warning' | 'inactive' | 'info'

const VARIANT_CLASSES: Record<StatusVariant, string> = {
  connected: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300',
  error: 'bg-red-50 text-red-700 ring-1 ring-red-200 dark:bg-red-900/30 dark:text-red-300',
  warning: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300',
  inactive: 'bg-muted text-muted-foreground ring-1 ring-border',
  info: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200 dark:bg-sky-900/30 dark:text-sky-300',
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
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium',
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current shrink-0" />
      {label}
    </span>
  )
}
