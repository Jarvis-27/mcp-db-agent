import Link from 'next/link'
import { ArrowUpRight } from 'lucide-react'
import { BrandMark } from '@/components/brand-mark'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

function GithubMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56 0-.27-.01-1.16-.02-2.1-3.2.69-3.87-1.36-3.87-1.36-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.76 2.69 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.18a10.94 10.94 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.05.78 2.12 0 1.53-.01 2.76-.01 3.13 0 .31.21.67.8.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  )
}

const navLinks = [
  { href: '/#how-it-works', label: 'How it works' },
  { href: '/#examples', label: 'Examples' },
  { href: '/#security', label: 'Security' },
  { href: '/pricing', label: 'Pricing' },
]

const footerNav: Array<{
  heading: string
  links: Array<{ href: string; label: string; external?: boolean }>
}> = [
  {
    heading: 'Product',
    links: [
      { href: '/#how-it-works', label: 'How it works' },
      { href: '/#examples', label: 'MCP examples' },
      { href: '/#security', label: 'Security' },
      { href: '/pricing', label: 'Pricing' },
    ],
  },
  {
    heading: 'Account',
    links: [
      { href: '/signup', label: 'Sign up' },
      { href: '/login', label: 'Sign in' },
      { href: '/app/dashboard', label: 'Dashboard' },
    ],
  },
  {
    heading: 'Resources',
    links: [
      { href: '/support', label: 'Support' },
      {
        href: 'https://modelcontextprotocol.io/',
        label: 'About MCP',
        external: true,
      },
      {
        href: 'https://github.com/anthropics',
        label: 'GitHub',
        external: true,
      },
      { href: '/#examples', label: 'Tool reference' },
    ],
  },
  {
    heading: 'Legal',
    links: [
      { href: '/privacy-policy', label: 'Privacy policy' },
      { href: '/terms-of-service', label: 'Terms of service' },
      { href: '/support', label: 'Refunds and cancellations' },
    ],
  },
]

export default function PublicLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="relative min-h-screen bg-background text-foreground">
      {/* ───────── Header ───────── */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-6 px-4 sm:px-6 lg:px-8">
          <BrandMark />

          <nav
            className="hidden items-center gap-1 rounded-full border border-border/70 bg-card/70 px-2 py-1 text-sm font-medium text-muted-foreground shadow-sm backdrop-blur md:flex"
            aria-label="Primary"
          >
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-full px-3 py-1.5 transition-colors hover:bg-background hover:text-foreground"
              >
                {link.label}
              </Link>
            ))}
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
              className={cn(
                buttonVariants({ size: 'lg' }),
                'h-9 px-4 group',
              )}
            >
              Start free
              <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>
          </div>
        </div>
      </header>

      {children}

      {/* ───────── Footer ───────── */}
      <footer className="relative overflow-hidden border-t border-foreground/15 bg-foreground text-background">
        <div
          aria-hidden
          className="pointer-events-none absolute -left-32 top-0 h-72 w-72 rounded-full bg-primary/30 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-32 bottom-0 h-72 w-72 rounded-full bg-accent/20 blur-3xl"
        />

        <div className="relative mx-auto max-w-7xl px-4 pb-12 pt-20 sm:px-6 lg:px-8">
          {/* Top: tagline + nav grid */}
          <div className="grid gap-12 lg:grid-cols-12">
            <div className="lg:col-span-5">
              <BrandMark inverse />
              <p className="mt-7 max-w-md font-display text-[1.7rem] font-semibold leading-[1.15] -tracking-[0.025em]">
                Plain-English questions, real database answers —{' '}
                <span className="text-background/60 font-normal">for everyone on the team.</span>
              </p>
              <p className="mt-5 max-w-md text-sm leading-7 text-background/65 text-pretty">
                PlainQuery is the customer-facing surface for the MCP Database
                Agent — an open-source server that lets any MCP client query
                your database safely.
              </p>
              <div className="mt-7 flex items-center gap-3">
                <Link
                  href="/signup"
                  className={cn(
                    buttonVariants({ variant: 'secondary', size: 'lg' }),
                    'h-10 px-5',
                  )}
                >
                  Start free
                  <ArrowUpRight className="h-4 w-4" />
                </Link>
                <Link
                  href="https://github.com"
                  className="inline-flex h-10 items-center gap-2 rounded-md px-4 text-sm font-medium text-background/80 ring-1 ring-inset ring-background/20 transition-colors hover:text-background"
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <GithubMark className="h-4 w-4" />
                  Source on GitHub
                </Link>
              </div>
            </div>

            <div className="lg:col-span-7">
              <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
                {footerNav.map((column) => (
                  <div key={column.heading}>
                    <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-background/55">
                      {column.heading}
                    </p>
                    <ul className="mt-5 space-y-3 text-sm">
                      {column.links.map((link) => (
                        <li key={`${column.heading}-${link.label}`}>
                          {link.external ? (
                            <a
                              href={link.href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="group inline-flex items-center gap-1.5 text-background/75 transition-colors hover:text-background"
                            >
                              {link.label}
                              <ArrowUpRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
                            </a>
                          ) : (
                            <Link
                              href={link.href}
                              className="text-background/75 transition-colors hover:text-background"
                            >
                              {link.label}
                            </Link>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>

              {/* Status row */}
              <div className="mt-12 rounded-2xl border border-background/15 bg-background/[0.04] p-5">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-70 animate-ping" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
                    </span>
                    <p className="font-mono text-xs uppercase tracking-[0.16em] text-background/75">
                      All systems normal · 99.97% / 30d
                    </p>
                  </div>
                  <Link
                    href="/#security"
                    className="inline-flex items-center gap-1 text-xs font-medium text-background/80 hover:text-background"
                  >
                    View security model
                    <ArrowUpRight className="h-3 w-3" />
                  </Link>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom rule + meta */}
          <div className="mt-16 flex flex-col gap-5 border-t border-background/15 pt-7 text-xs text-background/55 md:flex-row md:items-center md:justify-between">
            <p className="font-mono uppercase tracking-[0.16em]">
              © {new Date().getFullYear()} · plainquery · made for the model context protocol
            </p>
            <div className="flex flex-wrap items-center gap-5">
              <Link
                href="/pricing"
                className="transition-colors hover:text-background"
              >
                Pricing
              </Link>
              <Link
                href="/support"
                className="transition-colors hover:text-background"
              >
                Support
              </Link>
              <Link
                href="/privacy-policy"
                className="transition-colors hover:text-background"
              >
                Privacy
              </Link>
              <Link
                href="/terms-of-service"
                className="transition-colors hover:text-background"
              >
                Terms
              </Link>
              <Link
                href="/login"
                className="transition-colors hover:text-background"
              >
                Sign in
              </Link>
              <a
                href="mailto:hello@plainquery.app"
                className="transition-colors hover:text-background"
              >
                hello@plainquery.app
              </a>
            </div>
          </div>

          {/* Oversized wordmark */}
          <p
            aria-hidden
            className="pointer-events-none mt-12 select-none text-center font-display text-[clamp(4rem,16vw,14rem)] font-semibold leading-none -tracking-[0.05em] text-background/[0.07]"
          >
            PlainQuery<span className="text-primary/40">.</span>
          </p>
        </div>
      </footer>
    </div>
  )
}
