import type { ComponentType, ReactNode } from 'react'
import type { LucideProps } from 'lucide-react'
import { cn } from '@/lib/utils'

interface MetricCardProps {
  label: string
  value: ReactNode
  detail?: ReactNode
  icon?: ComponentType<LucideProps>
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'info'
  className?: string
}

const TONE_DOT: Record<NonNullable<MetricCardProps['tone']>, string> = {
  default: 'bg-muted-foreground/40',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  danger: 'bg-red-500',
  info: 'bg-primary',
}

const TONE_ICON: Record<NonNullable<MetricCardProps['tone']>, string> = {
  default: 'text-muted-foreground',
  success: 'text-emerald-700',
  warning: 'text-amber-700',
  danger: 'text-red-700',
  info: 'text-primary',
}

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = 'default',
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        'group relative overflow-hidden rounded-xl border border-border bg-card p-5 shadow-sm transition-colors hover:border-foreground/15',
        className,
      )}
    >
      {/* Tone rail — subtle ground for status without flooding the card */}
      <span
        aria-hidden
        className={cn('absolute inset-y-0 left-0 w-px', TONE_DOT[tone])}
      />

      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className={cn('h-1.5 w-1.5 rounded-full', TONE_DOT[tone])} />
          <p className="eyebrow text-muted-foreground">{label}</p>
        </div>
        {Icon && (
          <Icon className={cn('h-4 w-4', TONE_ICON[tone])} />
        )}
      </div>

      <div className="mt-4 font-display text-[1.7rem] font-semibold leading-tight -tracking-[0.025em] tabular-nums">
        {value}
      </div>

      {detail && (
        <div className="mt-1.5 text-xs leading-5 text-muted-foreground">
          {detail}
        </div>
      )}
    </div>
  )
}
