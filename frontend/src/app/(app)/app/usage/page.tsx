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
        eyebrow="Usage"
        title="Quota and question history"
        description="Understand how often connected clients are asking questions and whether anything is failing."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          label="Used today"
          value={quota ? quota.daily_used : '-'}
          detail={quota ? `${quota.daily_remaining} questions remaining` : 'Complete setup to activate quota'}
          icon={MessageSquareText}
          tone={quota && quota.daily_remaining === 0 ? 'danger' : 'success'}
        />
        <MetricCard
          label="Recent failures"
          value={failedCount}
          detail="Failed queries in the recent activity list"
          icon={XCircle}
          tone={failedCount > 0 ? 'warning' : 'success'}
        />
        <MetricCard
          label="Average duration"
          value={avgDuration == null ? '-' : `${avgDuration}ms`}
          detail="Measured across recent logged questions"
          icon={Timer}
          tone="info"
        />
      </div>

      {quota ? (
        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">Daily quota</h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Free plan users can ask 25 database questions per day. Pro will raise this to 500.
              </p>
            </div>
            <div className="rounded-2xl bg-background px-4 py-3 text-sm ring-1 ring-border">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Plan
              </p>
              <p className="mt-1 font-semibold capitalize">{payload?.plan_code ?? 'free'}</p>
            </div>
          </div>
          <div className="mt-6">
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

      <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
        <div>
          <h2 className="text-lg font-semibold">Recent questions</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Each row reflects one natural-language question handled by the MCP server.
          </p>
        </div>

        {recentQueries && recentQueries.items.length > 0 ? (
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
                  <th className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground md:table-cell">
                    Attempts
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    Result
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
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
            className="mt-5"
          />
        )}
      </section>
    </div>
  )
}

function UsageRow({ item }: { item: RecentQueryItem }) {
  const createdAt = new Date(item.created_at)
  return (
    <tr className="transition-colors hover:bg-muted/35">
      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
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
      <td className="hidden px-4 py-3 text-xs text-muted-foreground md:table-cell">
        {item.duration_ms != null ? `${item.duration_ms}ms` : 'Not recorded'}
      </td>
      <td className="hidden px-4 py-3 text-xs text-muted-foreground md:table-cell">
        {item.attempts > 1 ? (
          <span className="font-semibold text-amber-700">{item.attempts} attempts</span>
        ) : (
          '1 attempt'
        )}
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
  )
}
