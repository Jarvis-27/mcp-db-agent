import Link from 'next/link'
import {
  ArrowRight,
  CreditCard,
  ExternalLink,
  Gauge,
  MessageSquareText,
  ReceiptText,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { PageHeader } from '@/components/page-header'
import { MetricCard } from '@/components/metric-card'
import { StatusBadge } from '@/components/status-badge'
import { QuotaMeter } from '@/components/quota-meter'
import { buttonVariants } from '@/components/ui/button'
import { getBillingSummaryOrRedirect } from '@/lib/api/billing'
import { cn } from '@/lib/utils'
import { createCheckoutSessionAction, createPortalSessionAction } from './actions'

interface BillingPageProps {
  searchParams: Promise<{ checkout?: string; error?: string }>
}

export default async function BillingPage({ searchParams }: BillingPageProps) {
  const [billing, params] = await Promise.all([
    getBillingSummaryOrRedirect(),
    searchParams,
  ])
  const isPro = billing.plan_code === 'pro'
  const isPastDue = billing.billing_status === 'past_due'
  const quotaPct =
    billing.daily_limit > 0
      ? Math.round((billing.daily_used / billing.daily_limit) * 100)
      : 0

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="billing"
        title="Plan and billing"
        description="Stripe-confirmed billing controls the plan limits your MCP clients receive."
        action={
          billing.portal_available ? (
            <form action={createPortalSessionAction}>
              <button className={cn(buttonVariants({ size: 'lg' }), 'h-10')} type="submit">
                Manage billing
                <ExternalLink className="h-4 w-4" />
              </button>
            </form>
          ) : null
        }
      />

      {params.error && (
        <Notice
          tone="danger"
          title="Billing action failed"
          description={params.error}
        />
      )}

      {params.checkout === 'success' && (
        <Notice
          tone="success"
          title="Checkout complete"
          description="Your plan updates after Stripe sends the confirmation webhook."
        />
      )}

      {params.checkout === 'cancelled' && (
        <Notice
          tone="warning"
          title="Checkout cancelled"
          description="Your account is still on its previous plan."
        />
      )}

      {isPastDue && (
        <Notice
          tone="warning"
          title="Payment needs attention"
          description="Paid entitlements are restricted until Stripe confirms the subscription is healthy again."
        />
      )}

      {!billing.checkout_available && !billing.portal_available && !isPro && (
        <Notice
          tone="warning"
          title="Billing is not configured"
          description="Set the Stripe environment variables on the backend before accepting upgrades."
        />
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="plan"
          value={billing.plan_display_name}
          detail={isPro ? 'Paid entitlements active' : 'Free entitlements active'}
          icon={ShieldCheck}
          tone={isPro ? 'success' : 'info'}
        />
        <MetricCard
          label="billing"
          value={formatBillingStatus(billing.billing_status)}
          detail="Webhook-confirmed state"
          icon={ReceiptText}
          tone={billingStatusTone(billing.billing_status)}
        />
        <MetricCard
          label="questions today"
          value={`${billing.daily_used}/${billing.daily_limit}`}
          detail={`${billing.daily_remaining} remaining`}
          icon={MessageSquareText}
          tone={quotaPct >= 90 ? 'danger' : quotaPct >= 70 ? 'warning' : 'success'}
        />
        <MetricCard
          label="stripe"
          value={billing.stripe_customer_configured ? 'Linked' : 'Not linked'}
          detail={billing.portal_available ? 'Customer portal ready' : 'No portal session yet'}
          icon={CreditCard}
          tone={billing.stripe_customer_configured ? 'success' : 'default'}
        />
      </div>

      <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="eyebrow text-primary">current entitlement</p>
            <h2 className="mt-2 font-display text-lg font-semibold -tracking-[0.02em]">
              Daily question quota
            </h2>
            <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
              The MCP server reads this server-side plan before running database work.
            </p>
          </div>
          <StatusBadge
            variant={isPro ? 'connected' : isPastDue ? 'warning' : 'info'}
            label={`${billing.plan_code} plan`}
          />
        </div>
        <div className="mt-6 rounded-lg border border-border bg-muted/30 p-5">
          <QuotaMeter
            used={billing.daily_used}
            limit={billing.daily_limit}
            resetAt={new Date().toISOString()}
            warningLevel={quotaPct >= 100 ? 'critical' : quotaPct >= 80 ? 'high' : null}
          />
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <PlanPanel
          name="Free"
          price="$0"
          status={!isPro ? 'Current' : 'Available'}
          features={[
            '25 database questions per day',
            '1 active API key',
            '1 active database',
          ]}
        />
        <PlanPanel
          name="Pro"
          price="500 daily questions"
          status={isPro ? 'Current' : 'Upgrade'}
          featured
          features={[
            '500 database questions per day',
            '5 active API keys',
            '1 active database',
          ]}
          action={
            isPro ? (
              billing.portal_available ? (
                <form action={createPortalSessionAction}>
                  <button className={cn(buttonVariants({ variant: 'outline' }), 'w-full')} type="submit">
                    Open customer portal
                    <ExternalLink className="h-4 w-4" />
                  </button>
                </form>
              ) : null
            ) : billing.checkout_available ? (
              <form action={createCheckoutSessionAction}>
                <button className={cn(buttonVariants(), 'w-full')} type="submit">
                  Upgrade with Stripe
                  <ArrowRight className="h-4 w-4" />
                </button>
              </form>
            ) : (
              <Link href="/app/usage" className={cn(buttonVariants({ variant: 'outline' }), 'w-full')}>
                Review usage
                <Gauge className="h-4 w-4" />
              </Link>
            )
          }
        />
      </div>
    </div>
  )
}

function Notice({
  tone,
  title,
  description,
}: {
  tone: 'success' | 'warning' | 'danger'
  title: string
  description: string
}) {
  const classes = {
    success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
    warning: 'border-amber-200 bg-amber-50 text-amber-950',
    danger: 'border-red-200 bg-red-50 text-red-950',
  }
  return (
    <div className={cn('flex gap-3 rounded-xl border p-4', classes[tone])}>
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <p className="mt-1 text-sm opacity-80">{description}</p>
      </div>
    </div>
  )
}

function PlanPanel({
  name,
  price,
  status,
  features,
  featured,
  action,
}: {
  name: string
  price: string
  status: string
  features: string[]
  featured?: boolean
  action?: React.ReactNode
}) {
  return (
    <section
      className={cn(
        'rounded-xl border bg-card p-6 shadow-sm',
        featured ? 'border-foreground/25' : 'border-border',
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow text-primary">{status}</p>
          <h2 className="mt-2 font-display text-2xl font-semibold -tracking-[0.02em]">
            {name}
          </h2>
        </div>
        <p className="max-w-[12rem] text-right font-mono text-sm font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {price}
        </p>
      </div>
      <ul className="mt-6 space-y-3 text-sm">
        {features.map((feature) => (
          <li key={feature} className="flex items-start gap-2 text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>{feature}</span>
          </li>
        ))}
      </ul>
      {action && <div className="mt-6">{action}</div>}
    </section>
  )
}

function formatBillingStatus(status: string) {
  return status.replaceAll('_', ' ')
}

function billingStatusTone(status: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'active_paid' || status === 'trialing') return 'success'
  if (status === 'past_due') return 'warning'
  if (status === 'canceled') return 'danger'
  if (status === 'free') return 'info'
  return 'default'
}
