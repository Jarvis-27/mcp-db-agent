import { redirect } from 'next/navigation'
import { CheckCircle2, Clock3, MessageSquareText, Timer, XCircle } from 'lucide-react'
import { backendFetch } from '@/lib/api/backend'
import { QuotaMeter } from '@/components/quota-meter'
import { getRecentQueriesOrNull } from '@/lib/api/dashboard'
import { PageHeader } from '@/components/page-header'
import { MetricCard } from '@/components/metric-card'
import { EmptyState } from '@/components/empty-state'
import { cn } from '@/lib/utils'
import type { SetupPayloadResponse, RecentQueryItem } from '@/types/api'

export default async function UsagePage() {
  const [payloadRes, recentQueries] = await Promise.all([
    backendFetch('/v1/account/setup-payloads', {
      method: 'POST',
      body: JSON.stringify({ raw_api_key: null }),
      cache: 'no-store',
    }),
    getRecentQueriesOrNull(),
  ])

  if (payloadRes.status === 401) redirect('/login')

  const payload: SetupPayloadResponse | null = payloadRes.ok ? await payloadRes.json() : null
  const quota = payload?.quota_summary
  const failedCount = recentQueries?.items.filter((item) => !item.success).length ?? 0
  const avgDuration =
    recentQueries && recentQueries.items.length > 0
      ? Math.round(
          recentQueries.items.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0) /
            recentQueries.items.length,
        )
      : null

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="§ usage"
        title="Quota and question history"
        description="Understand how often connected clients are asking questions and whether anything is failing."
      />

      <div className="grid gap-3 md:grid-cols-3">
        <MetricCard
          label="used today"
          value={quota ? quota.daily_used : '—'}
          detail={
            quota
              ? `${quota.daily_remaining} remaining`
              : 'Complete setup to activate quota'
          }
          icon={MessageSquareText}
          tone={quota && quota.daily_remaining === 0 ? 'danger' : 'success'}
        />
        <MetricCard
          label="recent failures"
          value={failedCount}
          detail="Failed queries in the recent activity list"
          icon={XCircle}
          tone={failedCount > 0 ? 'warning' : 'success'}
        />
        <MetricCard
          label="avg duration"
          value={avgDuration == null ? '—' : `${avgDuration} ms`}
          detail="Measured across recent logged questions"
          icon={Timer}
          tone="info"
        />
      </div>

      {quota ? (
        <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="eyebrow text-primary">§ 01 · daily quota</p>
              <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
                Daily quota
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Free plan users can ask 25 database questions per day. Pro raises this to 500.
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/30 px-4 py-2.5">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Plan
              </p>
              <p className="mt-1 font-mono text-sm font-semibold capitalize">
                {payload?.plan_code ?? 'free'}
              </p>
            </div>
          </div>
          <div className="mt-6 rounded-lg border border-border bg-muted/30 p-5">
            <QuotaMeter
              used={quota.daily_used}
              limit={quota.daily_limit}
              resetAt={quota.reset_at}
              warningLevel={quota.warning_level}
            />
          </div>
        </section>
      ) : (
        <EmptyState
          icon={Clock3}
          title="Usage appears after setup"
          description="Connect your database and configure a client to start recording quota and query history."
        />
      )}

      <section className="rounded-xl border border-border bg-card shadow-sm">
        <div className="flex items-end justify-between border-b border-border px-6 py-4">
          <div>
            <p className="eyebrow text-primary">§ 02 · activity</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              Recent questions
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Each row is one natural-language question handled by the MCP server.
            </p>
          </div>
          {recentQueries && recentQueries.items.length > 0 && (
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground tabular-nums">
              {recentQueries.items.length} entries
            </span>
          )}
        </div>

        {recentQueries && recentQueries.items.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-muted/40">
                <tr>
                  <Th>Time</Th>
                  <Th>Question</Th>
                  <Th align="right" className="hidden md:table-cell">
                    Duration
                  </Th>
                  <Th align="right" className="hidden md:table-cell">
                    Attempts
                  </Th>
                  <Th align="right">Result</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {recentQueries.items.map((item) => (
                  <UsageRow key={item.id} item={item} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={MessageSquareText}
            title="No questions recorded yet"
            description="Query history appears here after you connect a client and ask your first question."
            className="m-6"
          />
        )}
      </section>
    </div>
  )
}

function UsageRow({ item }: { item: RecentQueryItem }) {
  const createdAt = new Date(item.created_at)
  return (
    <tr className="transition-colors hover:bg-muted/30">
      <td className="whitespace-nowrap px-4 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {createdAt.toLocaleString([], {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </td>
      <td className="max-w-sm truncate px-4 py-3 text-sm" title={item.question}>
        {item.question}
      </td>
      <td className="hidden px-4 py-3 text-right font-mono text-xs text-muted-foreground tabular-nums md:table-cell">
        {item.duration_ms != null ? `${item.duration_ms} ms` : '—'}
      </td>
      <td
        className={cn(
          'hidden px-4 py-3 text-right font-mono text-xs tabular-nums md:table-cell',
          item.attempts > 1 ? 'text-amber-700 font-semibold' : 'text-muted-foreground',
        )}
      >
        {item.attempts}×
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
