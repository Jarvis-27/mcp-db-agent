import { cn } from '@/lib/utils'

interface QuotaMeterProps {
  used: number
  limit: number
  resetAt: string
  warningLevel?: string | null
  compact?: boolean
}

export function QuotaMeter({ used, limit, resetAt, warningLevel, compact = false }: QuotaMeterProps) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0
  const barColor =
    pct >= 90 ? 'bg-red-500' : pct >= 70 || warningLevel ? 'bg-amber-500' : 'bg-emerald-500'
  const remaining = Math.max(limit - used, 0)

  const resetTime = new Date(resetAt).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })

  if (compact) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-medium">
            {used} / {limit}
          </span>
          <span className="text-xs text-muted-foreground">resets {resetTime}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={cn('h-full rounded-full transition-all', barColor)} style={{ width: `${pct}%` }} />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">
          {used} of {limit} daily questions used
        </span>
        <span className="text-xs text-muted-foreground">resets at {resetTime}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full transition-all', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">
        {remaining} remaining today
        {warningLevel && warningLevel !== 'none' && (
          <span className="ml-2 text-amber-600 dark:text-amber-400">
            - {warningLevel} warning
          </span>
        )}
      </p>
    </div>
  )
}
