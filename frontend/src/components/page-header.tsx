import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('border-b border-border pb-6', className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl">
          {eyebrow && (
            <div className="mb-3 flex items-center gap-2 text-primary">
              <span className="h-1 w-1 rounded-full bg-primary" />
              <span className="eyebrow">{eyebrow}</span>
            </div>
          )}
          <h1 className="font-display text-[1.75rem] font-semibold leading-[1.1] -tracking-[0.025em] text-foreground sm:text-[2rem]">
            {title}
          </h1>
          {description && (
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  )
}
