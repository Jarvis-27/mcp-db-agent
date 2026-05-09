import Link from 'next/link'
import { cn } from '@/lib/utils'

interface BrandMarkProps {
  href?: string
  compact?: boolean
  inverse?: boolean
  className?: string
}

export function BrandMark({ href = '/', compact = false, inverse = false, className }: BrandMarkProps) {
  const content = (
    <span className={cn('inline-flex items-center gap-3', className)}>
      <span
        className={cn(
          'relative flex h-9 w-9 items-center justify-center rounded-[10px] border shadow-sm',
          inverse
            ? 'border-white/20 bg-white/[0.06] text-primary-foreground'
            : 'border-foreground/10 bg-foreground text-background',
        )}
      >
        <span className="font-display text-[15px] font-bold leading-none -tracking-[0.04em]">
          PQ
        </span>
        <span
          className={cn(
            'absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full ring-2',
            inverse ? 'bg-primary ring-foreground' : 'bg-primary ring-background',
          )}
        />
      </span>
      {!compact && (
        <span className="leading-tight">
          <span
            className={cn(
              'block font-display text-[17px] font-semibold -tracking-[0.025em]',
            )}
          >
            PlainQuery
          </span>
          <span
            className={cn(
              'mt-0.5 block font-mono text-[10px] uppercase tracking-[0.22em]',
              inverse ? 'text-primary-foreground/65' : 'text-muted-foreground',
            )}
          >
            ask · sql · answer
          </span>
        </span>
      )}
    </span>
  )

  if (!href) return content

  return (
    <Link
      href={href}
      className="inline-flex rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      {content}
    </Link>
  )
}
