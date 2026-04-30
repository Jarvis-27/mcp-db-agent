import Link from 'next/link'
import { redirect } from 'next/navigation'
import { ArrowRight, CheckCircle2, Circle, Database, KeyRound, MailCheck, PlugZap } from 'lucide-react'
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

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Setup"
        title="Turn PlainQuery on, one step at a time."
        description="Connect the data source, set up client authentication, then copy the client-specific instructions."
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_0.8fr]">
        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="space-y-3">
            {steps.map((step, index) => {
              const Icon = step.icon
              return (
                <div
                  key={step.id}
                  className="flex items-start gap-4 rounded-2xl border bg-background/75 p-4"
                >
                  <span
                    className={cn(
                      'mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl',
                      step.done
                        ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
                        : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {step.done ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">
                        <span className="mr-2 text-xs text-muted-foreground">{index + 1}.</span>
                        {step.title}
                      </p>
                      <StatusBadge
                        variant={step.done ? 'connected' : step.manual ? 'info' : 'warning'}
                        label={step.done ? 'Done' : step.manual ? 'Manual' : 'Next'}
                      />
                    </div>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {step.description}
                    </p>
                  </div>
                  {step.action ? (
                    <Link
                      href={step.action.href}
                      className="hidden items-center gap-1 text-sm font-semibold text-primary sm:inline-flex"
                    >
                      {step.action.label}
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  ) : (
                    <Circle className="mt-3 hidden h-4 w-4 text-transparent sm:block" />
                  )}
                </div>
              )
            })}
          </div>
        </section>

        <aside className="rounded-3xl bg-primary p-6 text-primary-foreground shadow-xl shadow-primary/15">
          <h2 className="text-2xl font-semibold tracking-tight">First value is one good question.</h2>
          <p className="mt-3 text-sm leading-6 text-primary-foreground/80">
            Once setup is complete, ask something concrete from your client:
            &quot;What were the top customers by revenue last month?&quot;
          </p>
          <div className="mt-6 rounded-2xl bg-white/12 p-4 text-sm">
            <p className="font-semibold">Recommended next step</p>
            <p className="mt-1 text-primary-foreground/75">
              {dbConnected
                ? authReady
                  ? 'Copy a client configuration and test list_tables.'
                  : 'Create an API key or link OAuth before connecting a client.'
                : 'Connect your database and let PlainQuery validate the connection.'}
            </p>
          </div>
          <Link
            href={dbConnected ? (authReady ? '/app/setup/clients' : '/app/api-keys') : '/app/setup/database'}
            className={cn(buttonVariants({ variant: 'secondary', size: 'lg' }), 'mt-6 h-11 w-full')}
          >
            Continue setup
            <ArrowRight className="h-4 w-4" />
          </Link>
        </aside>
      </div>
    </div>
  )
}
