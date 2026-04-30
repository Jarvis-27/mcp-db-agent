import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { BrandMark } from '@/components/brand-mark'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export default function PublicLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b bg-background/92 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <BrandMark />
          <nav className="hidden items-center gap-7 text-sm font-medium text-muted-foreground md:flex">
            <Link href="/#how-it-works" className="transition-colors hover:text-foreground">
              How it works
            </Link>
            <Link href="/#security" className="transition-colors hover:text-foreground">
              Security
            </Link>
            <Link href="/pricing" className="transition-colors hover:text-foreground">
              Pricing
            </Link>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground sm:inline-flex"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className={cn(buttonVariants({ size: 'lg' }), 'h-9')}
            >
              Start free
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </header>
      {children}
      <footer className="border-t bg-card/40">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-sm text-muted-foreground sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <BrandMark compact />
          <p>
            PlainQuery is the customer-facing SaaS experience for MCP Database Agent.
          </p>
        </div>
      </footer>
    </div>
  )
}
