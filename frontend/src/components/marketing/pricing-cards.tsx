import Link from 'next/link'
import { Check, Clock, Sparkles } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const plans = [
  {
    name: 'Free',
    eyebrow: 'Start asking',
    price: '$0',
    suffix: 'no card required',
    description: 'Enough to connect one database and see whether plain-English querying clicks.',
    cta: 'Start free',
    href: '/signup',
    featured: false,
    features: [
      '25 database questions per day',
      '1 active API key',
      '1 active database',
      'ChatGPT, Cursor, VS Code, and HTTP MCP setup',
    ],
  },
  {
    name: 'Pro',
    eyebrow: 'Coming soon',
    price: '500',
    suffix: 'questions per day',
    description: 'Higher daily limits for people who make PlainQuery part of their daily workflow.',
    cta: 'Join early access',
    href: '/signup',
    featured: true,
    features: [
      '500 database questions per day',
      '5 active API keys',
      '1 active database',
      'Upgrade path when billing is enabled',
    ],
  },
]

export function PricingCards() {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {plans.map((plan) => (
        <div
          key={plan.name}
          className={cn(
            'rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border transition-transform hover:-translate-y-1',
            plan.featured && 'bg-primary text-primary-foreground ring-primary',
          )}
        >
          <div className="flex items-center justify-between gap-4">
            <div>
              <p
                className={cn(
                  'text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground',
                  plan.featured && 'text-primary-foreground/70',
                )}
              >
                {plan.eyebrow}
              </p>
              <h3 className="mt-2 text-2xl font-semibold tracking-tight">{plan.name}</h3>
            </div>
            <span
              className={cn(
                'flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary',
                plan.featured && 'bg-white/15 text-primary-foreground',
              )}
            >
              {plan.featured ? <Clock className="h-5 w-5" /> : <Sparkles className="h-5 w-5" />}
            </span>
          </div>

          <div className="mt-6">
            <div className="flex items-end gap-2">
              <span className="text-5xl font-semibold tracking-tight">{plan.price}</span>
              <span
                className={cn(
                  'pb-1 text-sm text-muted-foreground',
                  plan.featured && 'text-primary-foreground/70',
                )}
              >
                {plan.suffix}
              </span>
            </div>
            <p
              className={cn(
                'mt-4 min-h-12 text-sm leading-6 text-muted-foreground',
                plan.featured && 'text-primary-foreground/80',
              )}
            >
              {plan.description}
            </p>
          </div>

          <ul className="mt-6 space-y-3 text-sm">
            {plan.features.map((feature) => (
              <li key={feature} className="flex items-start gap-2">
                <Check className={cn('mt-0.5 h-4 w-4 text-emerald-600', plan.featured && 'text-emerald-200')} />
                <span>{feature}</span>
              </li>
            ))}
          </ul>

          <Link
            href={plan.href}
            className={cn(
              buttonVariants({ variant: plan.featured ? 'secondary' : 'default', size: 'lg' }),
              'mt-7 w-full',
            )}
          >
            {plan.cta}
          </Link>
        </div>
      ))}
    </div>
  )
}
