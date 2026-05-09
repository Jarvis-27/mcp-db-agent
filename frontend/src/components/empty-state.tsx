import type { ComponentType, ReactNode } from 'react'
import type { LucideProps } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: ComponentType<LucideProps>
  title: string
  description: string
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 px-6 py-10 text-center',
        className,
      )}
    >
      {Icon && (
        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
      )}
      <h2 className="font-display text-base font-semibold -tracking-[0.02em]">
        {title}
      </h2>
      <p className="mx-auto mt-1.5 max-w-sm text-sm leading-6 text-muted-foreground">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
