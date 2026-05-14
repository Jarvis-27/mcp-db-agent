'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState } from 'react'
import {
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareText,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import { BrandMark } from '@/components/brand-mark'
import { cn } from '@/lib/utils'

const ADMIN_NAV_ITEMS = [
  { href: '/admin', label: 'Overview', icon: LayoutDashboard, key: 'overview' },
  { href: '/admin/users', label: 'Users', icon: Users, key: 'users' },
  { href: '/admin/queries', label: 'Queries', icon: MessageSquareText, key: 'queries' },
] as const

interface AdminShellProps {
  children: React.ReactNode
  adminEmail: string
}

export function AdminShell({ children, adminEmail }: AdminShellProps) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin'
    return pathname === href || pathname.startsWith(href + '/')
  }

  return (
    <div className="min-h-screen bg-muted/40">
      {mobileOpen && (
        <button
          aria-label="Close navigation overlay"
          className="fixed inset-0 z-40 bg-foreground/30 backdrop-blur-[1px] lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-sidebar lg:translate-x-0',
          'transition-transform duration-200',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center justify-between border-b border-border px-5">
          <BrandMark href="/admin" />
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="rounded-md p-1.5 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 px-5 pt-6">
          <span className="inline-flex h-5 items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
            <ShieldCheck className="h-3 w-3" />
            Operator
          </span>
        </div>
        <p
          className="mt-2 truncate px-5 text-xs text-muted-foreground"
          title={adminEmail}
        >
          {adminEmail}
        </p>

        <nav className="mt-4 flex-1 overflow-y-auto px-3" aria-label="Admin">
          <ul className="space-y-0.5">
            {ADMIN_NAV_ITEMS.map((item, i) => {
              const active = isActive(item.href)
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={cn(
                      'group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                      active
                        ? 'bg-card text-sidebar-foreground shadow-[inset_0_0_0_1px] shadow-border'
                        : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'absolute inset-y-1.5 left-0 w-[2px] rounded-r-full transition-colors',
                        active ? 'bg-primary' : 'bg-transparent',
                      )}
                    />
                    <item.icon
                      className={cn(
                        'h-4 w-4 shrink-0 transition-colors',
                        active
                          ? 'text-primary'
                          : 'text-sidebar-foreground/50 group-hover:text-sidebar-foreground',
                      )}
                    />
                    <span className={cn('font-medium', active && 'font-semibold')}>
                      {item.label}
                    </span>
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/60">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        <div className="space-y-1 border-t border-border p-3">
          <Link
            href="/app/dashboard"
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            <LayoutDashboard className="h-4 w-4 shrink-0 text-sidebar-foreground/50" />
            Back to user app
          </Link>
          <form method="POST" action="/auth/signout">
            <button
              type="submit"
              className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              <LogOut className="h-4 w-4 shrink-0 text-sidebar-foreground/50" />
              Sign out
            </button>
          </form>
        </div>
      </aside>

      <div className="flex min-h-screen flex-col lg:pl-64">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/85 px-4 backdrop-blur lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <BrandMark compact href="/admin" />
          <span aria-hidden className="h-5 w-5" />
        </header>

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  )
}
