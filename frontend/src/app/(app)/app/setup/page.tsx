import Link from 'next/link'
import { redirect } from 'next/navigation'
import {
  ArrowRight,
  CheckCircle2,
  Database,
  KeyRound,
  MailCheck,
  PlugZap,
} from 'lucide-react'
import { backendFetch } from '@/lib/api/backend'
import { getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { getMcpOauthLinkStatusOrRedirect } from '@/lib/api/mcp-oauth'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ApiKeyResponse } from '@/types/api'

export default async function SetupPage() {
  const status = await getOnboardingStatusOrRedirect()

  if (status.account_status !== 'active') {
    redirect('/setup/status')
  }

  const isSetupComplete = status.status === 'setup_complete'
  let activeKeyCount = 0
  let isOauthLinked = false

  if (isSetupComplete) {
    const [keysRes, oauthRes] = await Promise.all([
      backendFetch('/v1/account/api-keys', { cache: 'no-store' }),
      getMcpOauthLinkStatusOrRedirect().catch(() => null),
    ])
    if (keysRes.ok) {
      const keys: ApiKeyResponse[] = await keysRes.json()
      activeKeyCount = keys.filter((key) => key.revoked_at === null).length
    }
    isOauthLinked = oauthRes?.linked ?? false
  }

  const emailVerified = status.status !== 'pending_email_verification'
  const dbConnected = isSetupComplete
  const authReady = activeKeyCount > 0 || isOauthLinked

  const steps = [
    {
      id: 'email',
      title: 'Verify email',
      description: 'Your browser session is trusted after email verification.',
      done: emailVerified,
      icon: MailCheck,
      action: null,
    },
    {
      id: 'database',
      title: 'Connect database',
      description: dbConnected
        ? 'Your primary database is connected and ready for guarded queries.'
        : 'Add a PostgreSQL or MySQL connection string and PlainQuery will test it.',
      done: dbConnected,
      icon: Database,
      action: dbConnected ? null : { href: '/app/setup/database', label: 'Connect database' },
    },
    {
      id: 'auth',
      title: 'Prepare client auth',
      description: isOauthLinked
        ? 'OAuth identity linked for remote MCP clients.'
        : activeKeyCount > 0
          ? `${activeKeyCount} active API key${activeKeyCount === 1 ? '' : 's'} available.`
          : 'Create an API key or link OAuth so your MCP client can authenticate.',
      done: authReady,
      icon: KeyRound,
      action:
        authReady || !isSetupComplete
          ? null
          : { href: '/app/api-keys', label: 'Set up auth' },
    },
    {
      id: 'client',
      title: 'Connect your AI client',
      description: 'Copy guided setup for ChatGPT, Cursor, VS Code, or generic HTTP MCP.',
      done: false,
      icon: PlugZap,
      action: isSetupComplete ? { href: '/app/setup/clients', label: 'Open client setup' } : null,
      manual: true,
    },
  ]

  const continueHref = dbConnected
    ? authReady
      ? '/app/setup/clients'
      : '/app/api-keys'
    : '/app/setup/database'

  const continueCopy = dbConnected
    ? authReady
      ? 'Copy a client configuration and test list_tables.'
      : 'Create an API key or link OAuth before connecting a client.'
    : 'Connect your database and let PlainQuery validate it.'

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="§ setup"
        title="Turn PlainQuery on, one step at a time."
        description="Connect the data source, set up client authentication, then copy the client-specific instructions."
      />

      <div className="grid gap-5 xl:grid-cols-[1fr_0.8fr]">
        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-6 py-4">
            <div>
              <p className="eyebrow text-primary">checklist</p>
              <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
                What still needs to be done
              </h2>
            </div>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground tabular-nums">
              {steps.filter((s) => s.done).length} / {steps.length} complete
            </span>
          </div>

          <ol className="divide-y divide-border">
            {steps.map((step, index) => {
              const Icon = step.icon
              return (
                <li
                  key={step.id}
                  className="grid grid-cols-[auto_1fr_auto] items-start gap-4 px-6 py-5"
                >
                  <span
                    className={cn(
                      'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md font-mono text-xs font-semibold',
                      step.done
                        ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
                        : 'bg-muted text-muted-foreground ring-1 ring-border',
                    )}
                  >
                    {step.done ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <Icon className="h-4 w-4" />
                    )}
                  </span>

                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <p className="text-sm font-semibold">
                        <span className="mr-2 font-mono text-[11px] font-normal text-muted-foreground">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        {step.title}
                      </p>
                      <StatusBadge
                        variant={step.done ? 'connected' : step.manual ? 'info' : 'warning'}
                        label={step.done ? 'Done' : step.manual ? 'Manual' : 'Next'}
                      />
                    </div>
                    <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                      {step.description}
                    </p>
                  </div>

                  {step.action ? (
                    <Link
                      href={step.action.href}
                      className="hidden items-center gap-1.5 self-center font-mono text-[11px] uppercase tracking-[0.14em] text-primary sm:inline-flex"
                    >
                      {step.action.label}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  ) : (
                    <span aria-hidden className="hidden h-4 w-16 sm:block" />
                  )}
                </li>
              )
            })}
          </ol>
        </section>

        <aside className="flex flex-col rounded-xl border border-foreground/95 bg-foreground p-6 text-background shadow-sm">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-background/55">
            the goal
          </p>
          <h2 className="mt-2 font-display text-2xl font-semibold leading-tight -tracking-[0.025em]">
            First value is one good question.
          </h2>
          <p className="mt-3 text-sm leading-6 text-background/70">
            Once setup is complete, ask something concrete from your client:
            &quot;What were the top customers by revenue last month?&quot;
          </p>

          <div className="mt-5 rounded-lg border border-background/15 bg-background/[0.06] p-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-background/55">
              Recommended next step
            </p>
            <p className="mt-2 text-sm leading-6 text-background/85">
              {continueCopy}
            </p>
          </div>

          <Link
            href={continueHref}
            className={cn(
              buttonVariants({ variant: 'secondary', size: 'lg' }),
              'mt-6 h-11 w-full justify-between',
            )}
          >
            Continue setup
            <ArrowRight className="h-4 w-4" />
          </Link>
        </aside>
      </div>
    </div>
  )
}
