import Link from 'next/link'
import {
  ArrowRight,
  ArrowUpRight,
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
        eyebrow="§ workspace"
        title="Dashboard"
        description="A quick read on whether PlainQuery is ready to answer database questions."
        action={
          <Link
            href="/app/setup/clients"
            className={cn(buttonVariants({ size: 'lg' }), 'h-10')}
          >
            Connect client
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        }
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="database"
          value={isSetupComplete ? 'Connected' : 'Not connected'}
          detail={
            isSetupComplete
              ? `${status?.plan_code ?? 'free'} plan active`
              : 'Connect Postgres or MySQL'
          }
          icon={Database}
          tone={isSetupComplete ? 'success' : 'warning'}
        />
        <MetricCard
          label="auth"
          value={authReady ? 'Ready' : 'Needs setup'}
          detail={
            isOauthLinked
              ? oauth?.oauth_email ?? 'OAuth account linked'
              : hasActiveKey
                ? `${activeKeys.length} API key${activeKeys.length === 1 ? '' : 's'} active`
                : 'No client auth yet'
          }
          icon={Shield}
          tone={authReady ? 'success' : 'warning'}
        />
        <MetricCard
          label="questions today"
          value={`${dailyUsed}/${dailyLimit || '—'}`}
          detail={
            payload
              ? `${payload.quota_summary.daily_remaining} remaining`
              : 'Complete setup to see quota'
          }
          icon={MessageSquareText}
          tone={quotaTone}
        />
        <MetricCard
          label="recent activity"
          value={recentQueries?.items.length ?? 0}
          detail="Queries logged from MCP clients"
          icon={Clock3}
          tone="info"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <SectionCard
          eyebrow="§ 01 · setup path"
          title="What it takes to ask a question"
          description="These are the pieces that turn PlainQuery from an account into a usable database agent."
          action={
            nextAction && (
              <Link
                href={nextAction.href}
                className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-primary"
              >
                {nextAction.label}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )
          }
        >
          <ol className="-mx-1 mt-5 divide-y divide-border">
            {readiness.map((item, index) => (
              <li key={item.label}>
                <Link
                  href={item.href}
                  className="group flex items-center gap-4 px-1 py-3 transition-colors hover:bg-muted/40"
                >
                  <span
                    className={cn(
                      'flex h-8 w-8 items-center justify-center rounded-md text-xs font-mono font-semibold',
                      item.ready
                        ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
                        : 'bg-muted text-muted-foreground ring-1 ring-border',
                    )}
                  >
                    {item.ready ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      String(index + 1).padStart(2, '0')
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium">{item.label}</p>
                      <StatusBadge
                        variant={item.ready ? 'connected' : 'warning'}
                        label={item.ready ? 'Ready' : 'Action'}
                      />
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {item.detail}
                    </p>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground" />
                </Link>
              </li>
            ))}
          </ol>
        </SectionCard>

        <SectionCard
          eyebrow="§ 02 · endpoint"
          title="MCP endpoint"
          description="Point supported clients at this URL after auth is configured."
        >
          {payload?.mcp_url ? (
            <div className="mt-5 space-y-5">
              <CodeBlockWithCopy code={payload.mcp_url} inline />
              <div className="rounded-lg border border-border bg-muted/30 p-4">
                <QuotaMeter
                  used={payload.quota_summary.daily_used}
                  limit={payload.quota_summary.daily_limit}
                  resetAt={payload.quota_summary.reset_at}
                  warningLevel={payload.quota_summary.warning_level}
                />
              </div>
            </div>
          ) : (
            <EmptyState
              icon={Database}
              title="Endpoint appears after setup"
              description="Connect a database first. The dashboard will show your generated MCP URL and quota."
              className="mt-5"
            />
          )}
        </SectionCard>
      </div>

      <SectionCard
        eyebrow="§ 03 · activity"
        title="Recent questions"
        description="A lightweight audit trail of what your connected clients asked."
        action={
          recentQueries && recentQueries.items.length > 0 ? (
            <Link
              href="/app/usage"
              className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-primary"
            >
              View all usage
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          ) : null
        }
      >
        {recentQueries && recentQueries.items.length > 0 ? (
          <RecentQueriesTable items={recentQueries.items.slice(0, 6)} />
        ) : (
          <EmptyState
            icon={MessageSquareText}
            title="No questions yet"
            description="Once you connect a client and ask your first database question, the activity will appear here."
            action={
              <Link
                href="/app/setup/clients"
                className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
              >
                Connect a client
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
            className="mt-5"
          />
        )}
      </SectionCard>
    </div>
  )
}

function SectionCard({
  eyebrow,
  title,
  description,
  action,
  children,
}: {
  eyebrow: string
  title: string
  description?: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="eyebrow text-primary">{eyebrow}</p>
          <h2 className="mt-2 font-display text-lg font-semibold -tracking-[0.02em]">
            {title}
          </h2>
          {description && (
            <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children}
    </section>
  )
}

function RecentQueriesTable({ items }: { items: RecentQueryItem[] }) {
  return (
    <div className="mt-5 overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40">
          <tr>
            <Th>Time</Th>
            <Th>Question</Th>
            <Th align="right" className="hidden md:table-cell">
              Duration
            </Th>
            <Th align="right">Result</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-card">
          {items.map((item) => (
            <tr key={item.id} className="transition-colors hover:bg-muted/30">
              <td className="whitespace-nowrap px-4 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                {formatRelativeTime(item.created_at)}
              </td>
              <td
                className="max-w-sm truncate px-4 py-3 text-sm"
                title={item.question}
              >
                {item.question}
              </td>
              <td className="hidden px-4 py-3 text-right font-mono text-xs text-muted-foreground tabular-nums md:table-cell">
                {item.duration_ms != null ? `${item.duration_ms} ms` : '—'}
              </td>
              <td className="px-4 py-3 text-right">
                {item.success ? (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700">
                    <CheckCircle2 className="h-3 w-3" />
                    success
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.14em] text-red-700">
                    <XCircle className="h-3 w-3" />
                    failed
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Th({
  children,
  align,
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  className?: string
}) {
  return (
    <th
      className={cn(
        'px-4 py-2.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
    >
      {children}
    </th>
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
