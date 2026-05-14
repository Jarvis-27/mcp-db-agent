import Link from 'next/link'
import { Activity, AlertTriangle, Gauge, Users } from 'lucide-react'
import { MetricCard } from '@/components/metric-card'
import { PageHeader } from '@/components/page-header'
import { Sparkline } from '@/components/admin/sparkline'
import { getAdminOverview, getAdminQueries } from '@/lib/api/admin'
import {
  formatDuration,
  formatNumber,
  formatPercent,
  formatRelativeTime,
} from '@/lib/admin-format'

export default async function AdminOverviewPage() {
  const overview = await getAdminOverview()
  const recentErrors = await getAdminQueries({ success: 'false', limit: 5 })

  if (!overview) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Operator"
          title="Overview"
          description="Aggregate health across all users."
        />
        <p className="text-sm text-muted-foreground">
          Overview is temporarily unavailable.
        </p>
      </div>
    )
  }

  const errorRateTone =
    overview.error_rate_today >= 0.05
      ? 'danger'
      : overview.error_rate_today >= 0.01
        ? 'warning'
        : 'success'

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operator"
        title="Overview"
        description="Aggregate user, query, and latency health across the deployment."
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          icon={Users}
          label="Total users"
          value={formatNumber(overview.users_total)}
          detail={
            <>
              {formatNumber(overview.users_active_7d)} active in last 7 days ·{' '}
              {formatNumber(overview.users_by_status.suspended)} suspended ·{' '}
              {formatNumber(overview.users_by_status.closed)} closed
            </>
          }
        />
        <MetricCard
          icon={Activity}
          label="Queries today"
          value={formatNumber(overview.queries_today)}
          detail={`${formatNumber(overview.users_by_status.pending_email_verification)} pending email verification`}
        />
        <MetricCard
          icon={AlertTriangle}
          label="Error rate today"
          tone={errorRateTone}
          value={formatPercent(overview.error_rate_today)}
          detail={
            overview.queries_today === 0
              ? 'No queries logged yet'
              : `Across ${formatNumber(overview.queries_today)} queries`
          }
        />
        <MetricCard
          icon={Gauge}
          label="p95 latency today"
          value={formatDuration(overview.p95_duration_ms_today)}
          detail={`p50: ${formatDuration(overview.p50_duration_ms_today)}`}
        />
      </div>

      <section className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-lg font-semibold">14-day query volume</h2>
          <p className="text-xs text-muted-foreground">
            {overview.daily_query_counts.reduce((a, c) => a + c.total, 0).toLocaleString()}{' '}
            queries
          </p>
        </div>
        <div className="mt-4 text-primary">
          <Sparkline
            values={overview.daily_query_counts.map((d) => d.total)}
            width={800}
            height={80}
            className="w-full"
            ariaLabel="Daily query volume sparkline"
          />
        </div>
        <ul className="mt-3 grid grid-cols-7 gap-1 text-[10px] text-muted-foreground sm:grid-cols-14">
          {overview.daily_query_counts.map((d) => (
            <li key={d.date} className="text-center font-mono">
              <span className="block">{d.date.slice(5)}</span>
              <span className="block text-foreground/80">{d.total}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">Recent errors</h2>
          <Link
            href="/admin/queries?success=false"
            className="text-xs font-medium text-primary hover:underline"
          >
            View all →
          </Link>
        </div>
        {recentErrors && recentErrors.items.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-6 py-3 font-medium">When</th>
                <th className="px-6 py-3 font-medium">User</th>
                <th className="px-6 py-3 font-medium">Question</th>
                <th className="px-6 py-3 font-medium">Error</th>
              </tr>
            </thead>
            <tbody>
              {recentErrors.items.map((q) => (
                <tr key={q.id} className="border-t border-border align-top">
                  <td className="px-6 py-3 text-muted-foreground">
                    {formatRelativeTime(q.timestamp)}
                  </td>
                  <td className="px-6 py-3">
                    <Link
                      href={`/admin/users/${q.user_id}`}
                      className="text-primary hover:underline"
                    >
                      {q.user_email ?? q.user_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-6 py-3 max-w-xs truncate">{q.question}</td>
                  <td className="px-6 py-3 text-xs text-destructive/80">
                    {q.error_code ?? q.error ?? 'error'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-6 py-8 text-sm text-muted-foreground">
            No errors logged today.
          </p>
        )}
      </section>
    </div>
  )
}
