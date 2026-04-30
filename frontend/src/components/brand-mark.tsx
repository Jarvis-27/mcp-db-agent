import Link from 'next/link'
import { DatabaseZap } from 'lucide-react'
import { cn } from '@/lib/utils'

interface BrandMarkProps {
  href?: string
  compact?: boolean
  className?: string
}

export function BrandMark({ href = '/', compact = false, className }: BrandMarkProps) {
  const content = (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
        <DatabaseZap className="h-4 w-4" />
      </span>
      {!compact && (
        <span className="leading-none">
          <span className="block text-sm font-semibold tracking-tight">PlainQuery</span>
          <span className="mt-1 block text-[11px] font-medium text-muted-foreground">
            MCP Database Agent
          </span>
        </span>
      )}
    </span>
  )

  if (!href) return content

  return (
    <Link href={href} className="inline-flex rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50">
      {content}
    </Link>
  )
}
