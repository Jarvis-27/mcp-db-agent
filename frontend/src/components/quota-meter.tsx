import { cn } from '@/lib/utils'

interface QuotaMeterProps {
  used: number
  limit: number
  resetAt: string
  warningLevel?: string | null
  compact?: boolean
}

export function QuotaMeter({
  used,
  limit,
  resetAt,
  warningLevel,
  compact = false,
}: QuotaMeterProps) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0
  const barColor =
    pct >= 90
      ? 'bg-red-500'
      : pct >= 70 || warningLevel
        ? 'bg-amber-500'
        : 'bg-primary'
  const remaining = Math.max(limit - used, 0)
  const resetTime = new Date(resetAt).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })

  if (compact) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2 font-mono text-xs">
          <span className="tabular-nums text-foreground">
            {used.toLocaleString()} / {limit.toLocaleString()}
          </span>
          <span className="uppercase tracking-[0.12em] text-muted-foreground">
            resets {resetTime}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn('h-full rounded-full transition-all duration-500', barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2 font-mono">
          <span className="text-base font-semibold tabular-nums text-foreground">
            {used.toLocaleString()}
          </span>
          <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
            of {limit.toLocaleString()} used today
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          resets {resetTime}
        </span>
      </div>

      <div className="relative h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full rounded-full transition-all duration-500', barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        <span className="tabular-nums text-foreground">{remaining.toLocaleString()}</span>{' '}
        remaining
        {warningLevel && warningLevel !== 'none' && (
          <span className="ml-3 text-amber-700 dark:text-amber-400">
            · {warningLevel} warning
          </span>
        )}
      </p>
    </div>
  )
}
