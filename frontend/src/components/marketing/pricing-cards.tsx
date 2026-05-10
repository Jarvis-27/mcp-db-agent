import Link from 'next/link'
import { ArrowUpRight, Check } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const plans = [
  {
    name: 'Free',
    eyebrow: '00 · start',
    price: '$0',
    suffix: 'forever, no card',
    description:
      'Connect one database, plug in an MCP client, and see whether plain-English querying clicks for your team.',
    cta: 'Start free',
    href: '/signup',
    featured: false,
    features: [
      '25 database questions per day',
      '1 active API key',
      '1 active database',
      'ChatGPT, Cursor, VS Code, HTTP MCP setup',
    ],
  },
  {
    name: 'Pro',
    eyebrow: '01 · scale',
    price: '500',
    suffix: '/ daily questions',
    description:
      'Higher daily limits and additional keys — for the moment PlainQuery becomes part of your workflow, not a curiosity.',
    cta: 'Start free',
    href: '/signup',
    featured: true,
    features: [
      '500 database questions per day',
      '5 active API keys',
      '1 active database',
      'Upgrade through Stripe after setup',
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
            'group relative flex flex-col rounded-3xl border bg-card p-7 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-foreground/5',
            plan.featured &&
              'border-foreground/95 bg-foreground text-background shadow-[0_30px_70px_-20px_rgba(15,23,41,0.45)]',
          )}
        >
          {plan.featured && (
            <span className="absolute -top-3 left-7 inline-flex items-center gap-1.5 rounded-full bg-primary px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary-foreground shadow-md">
              <span className="h-1.5 w-1.5 rounded-full bg-primary-foreground" />
              Recommended
            </span>
          )}

          <div className="flex items-baseline justify-between">
            <span
              className={cn(
                'eyebrow',
                plan.featured ? 'text-background/55' : 'text-muted-foreground',
              )}
            >
              {plan.eyebrow}
            </span>
            <h3 className="font-display text-2xl font-semibold -tracking-[0.025em]">
              {plan.name}
            </h3>
          </div>

          <div className="mt-6 flex items-end gap-2">
            <span className="font-display text-6xl font-semibold leading-none -tracking-[0.04em]">
              {plan.price}
            </span>
            <span
              className={cn(
                'pb-1 font-mono text-xs uppercase tracking-[0.12em]',
                plan.featured ? 'text-background/55' : 'text-muted-foreground',
              )}
            >
              {plan.suffix}
            </span>
          </div>

          <p
            className={cn(
              'mt-5 min-h-12 text-sm leading-7',
              plan.featured ? 'text-background/75' : 'text-muted-foreground',
            )}
          >
            {plan.description}
          </p>

          <ul className="mt-6 space-y-3 text-sm">
            {plan.features.map((feature) => (
              <li key={feature} className="flex items-start gap-3">
                <Check
                  className={cn(
                    'mt-0.5 h-4 w-4 flex-none',
                    plan.featured ? 'text-primary' : 'text-primary',
                  )}
                />
                <span>{feature}</span>
              </li>
            ))}
          </ul>

          <Link
            href={plan.href}
            className={cn(
              buttonVariants({
                variant: plan.featured ? 'secondary' : 'default',
                size: 'lg',
              }),
              'mt-7 w-full justify-between',
            )}
          >
            {plan.cta}
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>
      ))}
    </div>
  )
}
