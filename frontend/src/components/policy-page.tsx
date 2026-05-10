import Link from 'next/link'
import { ArrowUpRight } from 'lucide-react'

type PolicyPageProps = {
  eyebrow: string
  title: string
  intro: string
  updated: string
  children: React.ReactNode
}

type PolicySectionProps = {
  title: string
  children: React.ReactNode
}

const relatedLinks = [
  { href: '/support', label: 'Support' },
  { href: '/privacy-policy', label: 'Privacy policy' },
  { href: '/terms-of-service', label: 'Terms of service' },
]

export function PolicyPage({
  eyebrow,
  title,
  intro,
  updated,
  children,
}: PolicyPageProps) {
  return (
    <main>
      <section className="border-b border-border bg-card/45">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              {eyebrow}
            </p>
            <h1 className="mt-4 text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
              {title}
            </h1>
            <p className="mt-6 text-lg leading-8 text-muted-foreground">
              {intro}
            </p>
            <p className="mt-5 font-mono text-xs uppercase tracking-[0.16em] text-muted-foreground">
              Last updated {updated}
            </p>
          </div>
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] lg:px-8 lg:py-20">
        <aside className="lg:sticky lg:top-28 lg:self-start">
          <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Customer links
          </p>
          <nav className="mt-4 grid gap-2" aria-label="Related policies">
            {relatedLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="inline-flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
              >
                {link.label}
                <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
              </Link>
            ))}
          </nav>
        </aside>

        <article className="max-w-3xl space-y-10">{children}</article>
      </section>
    </main>
  )
}

export function PolicySection({ title, children }: PolicySectionProps) {
  return (
    <section className="border-t border-border pt-8">
      <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
      <div className="mt-4 space-y-4 text-sm leading-7 text-muted-foreground [&_a]:font-medium [&_a]:text-primary [&_a:hover]:underline [&_li]:pl-1 [&_strong]:text-foreground">
        {children}
      </div>
    </section>
  )
}
