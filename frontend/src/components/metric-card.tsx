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

const toneClasses = {
  default: 'bg-card',
  success: 'bg-emerald-50/80 ring-emerald-200/80',
  warning: 'bg-amber-50/80 ring-amber-200/80',
  danger: 'bg-red-50/80 ring-red-200/80',
  info: 'bg-sky-50/80 ring-sky-200/80',
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
        'rounded-2xl p-5 text-sm shadow-sm ring-1 ring-border transition-transform hover:-translate-y-0.5',
        toneClasses[tone],
        className,
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {label}
        </p>
        {Icon && (
          <span className="rounded-full bg-background/75 p-2 text-primary ring-1 ring-border">
            <Icon className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-4 text-2xl font-semibold tracking-tight">{value}</div>
      {detail && <div className="mt-2 text-sm leading-5 text-muted-foreground">{detail}</div>}
    </div>
  )
}
