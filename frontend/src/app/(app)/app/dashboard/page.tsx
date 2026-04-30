import Link from 'next/link'
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  MessageSquareText,
  Shield,
  XCircle,
} from 'lucide-react'
import { getDashboardDataOrRedirect, getRecentQueriesOrNull } from '@/lib/api/dashboard'
import { StatusBadge } from '@/components/status-badge'
import { QuotaMeter } from '@/components/quota-meter'
import { CodeBlockWithCopy } from '@/components/code-block-with-copy'
import { PageHeader } from '@/components/page-header'
import { MetricCard } from '@/components/metric-card'
import { EmptyState } from '@/components/empty-state'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { RecentQueryItem } from '@/types/api'

export default async function DashboardPage() {
  const [{ status, payload, keys, oauth }, recentQueries] = await Promise.all([
    getDashboardDataOrRedirect(),
    getRecentQueriesOrNull(),
  ])

  const isSetupComplete = status?.status === 'setup_complete'
  const activeKeys = keys.filter((key) => key.revoked_at === null)
  const hasActiveKey = activeKeys.length > 0
  const isOauthLinked = oauth?.linked ?? false
  const authReady = hasActiveKey || isOauthLinked
  const dailyLimit = payload?.quota_summary.daily_limit ?? 0
  const dailyUsed = payload?.quota_summary.daily_used ?? 0
  const quotaPct = dailyLimit > 0 ? Math.round((dailyUsed / dailyLimit) * 100) : 0
  const quotaTone = quotaPct >= 90 ? 'danger' : quotaPct >= 70 ? 'warning' : 'success'
  const nextAction = getNextAction({ isSetupComplete, hasActiveKey, isOauthLinked })

  const readiness = [
    {
      label: 'Database',
      ready: isSetupComplete,
      detail: isSetupComplete ? 'Connected and queryable' : 'Connect your first database',
      href: '/app/setup/database',
    },
    {
      label: 'MCP auth',
      ready: authReady,
      detail: isOauthLinked
        ? 'OAuth identity linked'
        : hasActiveKey
          ? `${activeKeys.length} active API key${activeKeys.length === 1 ? '' : 's'}`
          : 'Create an API key or link OAuth',
      href: '/app/api-keys',
    },
    {
      label: 'Client',
      ready: isSetupComplete && authReady,
      detail: 'Copy setup for ChatGPT, Cursor, VS Code, or HTTP',
      href: '/app/setup/clients',
    },
  ]

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Workspace"
        title="Dashboard"
        description="A quick read on whether PlainQuery is ready to answer database questions."
        action={
          <Link href="/app/setup/clients" className={cn(buttonVariants({ size: 'lg' }), 'h-10')}>
            Connect client
            <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Database"
          value={isSetupComplete ? 'Connected' : 'Not connected'}
          detail={
            isSetupComplete
              ? `${status?.plan_code ?? 'free'} plan is active`
              : 'Connect PostgreSQL or MySQL to continue'
          }
          icon={Database}
          tone={isSetupComplete ? 'success' : 'warning'}
        />
        <MetricCard
          label="Auth"
          value={authReady ? 'Ready' : 'Needs setup'}
          detail={
            isOauthLinked
              ? oauth?.oauth_email ?? 'OAuth account linked'
              : hasActiveKey
                ? `${activeKeys.length} API key${activeKeys.length === 1 ? '' : 's'} active`
                : 'No client auth configured yet'
          }
          icon={Shield}
          tone={authReady ? 'success' : 'warning'}
        />
        <MetricCard
          label="Questions today"
          value={`${dailyUsed}/${dailyLimit || '-'}`}
          detail={payload ? `${payload.quota_summary.daily_remaining} remaining` : 'Complete setup to see quota'}
          icon={MessageSquareText}
          tone={quotaTone}
        />
        <MetricCard
          label="Recent activity"
          value={recentQueries?.items.length ?? 0}
          detail="Queries logged from connected MCP clients"
          icon={Clock3}
          tone="info"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">Setup path</h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                These are the pieces that turn PlainQuery from an account into a usable database agent.
              </p>
            </div>
            {nextAction && (
              <Link
                href={nextAction.href}
                className="inline-flex items-center gap-2 text-sm font-semibold text-primary"
              >
                {nextAction.label}
                <ArrowRight className="h-4 w-4" />
              </Link>
            )}
          </div>

          <div className="mt-6 space-y-3">
            {readiness.map((item, index) => (
              <Link
                key={item.label}
                href={item.href}
                className="flex items-start gap-4 rounded-2xl border bg-background/70 p-4 transition-colors hover:bg-muted/50"
              >
                <span
                  className={cn(
                    'mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl',
                    item.ready ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-muted text-muted-foreground',
                  )}
                >
                  {item.ready ? <CheckCircle2 className="h-5 w-5" /> : <span className="text-sm font-semibold">{index + 1}</span>}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{item.label}</span>
                    <StatusBadge
                      variant={item.ready ? 'connected' : 'warning'}
                      label={item.ready ? 'Ready' : 'Action needed'}
                    />
                  </span>
                  <span className="mt-1 block text-sm leading-6 text-muted-foreground">
                    {item.detail}
                  </span>
                </span>
                <ArrowRight className="mt-2 h-4 w-4 shrink-0 text-muted-foreground" />
              </Link>
            ))}
          </div>
        </section>

        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <h2 className="text-lg font-semibold">MCP endpoint</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Point supported clients at this endpoint after auth is ready.
          </p>
          {payload?.mcp_url ? (
            <div className="mt-5 space-y-5">
              <CodeBlockWithCopy code={payload.mcp_url} inline />
              <QuotaMeter
                used={payload.quota_summary.daily_used}
                limit={payload.quota_summary.daily_limit}
                resetAt={payload.quota_summary.reset_at}
                warningLevel={payload.quota_summary.warning_level}
              />
            </div>
          ) : (
            <EmptyState
              icon={Database}
              title="Endpoint appears after setup"
              description="Connect a database first. Then this dashboard will show your generated MCP URL and quota."
              className="mt-5"
            />
          )}
        </section>
      </div>

      <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Recent questions</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              A lightweight audit trail of what your connected clients asked.
            </p>
          </div>
          {recentQueries && recentQueries.items.length > 0 && (
            <Link href="/app/usage" className="text-sm font-semibold text-primary">
              View usage
            </Link>
          )}
        </div>

        {recentQueries && recentQueries.items.length > 0 ? (
          <RecentQueriesTable items={recentQueries.items.slice(0, 6)} />
        ) : (
          <EmptyState
            icon={MessageSquareText}
            title="No questions yet"
            description="Once you connect a client and ask your first database question, the activity will appear here."
            action={
              <Link href="/app/setup/clients" className={buttonVariants({ variant: 'outline' })}>
                Connect a client
                <ArrowRight className="h-4 w-4" />
              </Link>
            }
            className="mt-5"
          />
        )}
      </section>
    </div>
  )
}

function RecentQueriesTable({ items }: { items: RecentQueryItem[] }) {
  return (
    <div className="mt-5 overflow-hidden rounded-2xl border bg-background">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/60">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Time
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Question
            </th>
            <th className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground md:table-cell">
              Duration
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Result
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {items.map((item) => (
            <tr key={item.id} className="transition-colors hover:bg-muted/35">
              <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                {formatRelativeTime(item.created_at)}
              </td>
              <td className="max-w-sm truncate px-4 py-3 text-sm" title={item.question}>
                {item.question}
              </td>
              <td className="hidden px-4 py-3 text-xs text-muted-foreground md:table-cell">
                {item.duration_ms != null ? `${item.duration_ms}ms` : 'Not recorded'}
              </td>
              <td className="px-4 py-3 text-right">
                <span
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
                    item.success
                      ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
                      : 'bg-red-50 text-red-700 ring-1 ring-red-200',
                  )}
                >
                  {item.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                  {item.success ? 'Success' : 'Failed'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function getNextAction(opts: {
  isSetupComplete: boolean
  hasActiveKey: boolean
  isOauthLinked: boolean
}): { message: string; href: string; label: string } | null {
  if (!opts.isSetupComplete) {
    return {
      message: 'Connect your database to start querying.',
      href: '/app/setup/database',
      label: 'Connect database',
    }
  }
  if (!opts.hasActiveKey && !opts.isOauthLinked) {
    return {
      message: 'Create an API key or link OAuth so your MCP client can authenticate.',
      href: '/app/api-keys',
      label: 'Set up auth',
    }
  }
  return null
}
