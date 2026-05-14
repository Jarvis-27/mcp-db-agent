import Link from 'next/link'
import { PageHeader } from '@/components/page-header'
import { getAdminUsers } from '@/lib/api/admin'
import { formatDateTime, formatNumber, formatRelativeTime } from '@/lib/admin-format'
import type { AccountStatus } from '@/types/api'

type SearchParams = {
  q?: string
  status?: string
  plan?: string
  limit?: string
  offset?: string
}

const STATUS_OPTIONS: { value: '' | AccountStatus; label: string }[] = [
  { value: '', label: 'Any status' },
  { value: 'active', label: 'Active' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'closed', label: 'Closed' },
]

const STATUS_BADGE: Record<AccountStatus, string> = {
  active: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30',
  suspended: 'bg-amber-500/10 text-amber-700 border-amber-500/30',
  closed: 'bg-red-500/10 text-red-700 border-red-500/30',
}

export default async function AdminUsersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>
}) {
  const sp = await searchParams
  const limit = Math.min(100, Math.max(1, parseInt(sp.limit ?? '25', 10) || 25))
  const offset = Math.max(0, parseInt(sp.offset ?? '0', 10) || 0)

  const data = await getAdminUsers({
    q: sp.q,
    status: sp.status,
    plan: sp.plan,
    limit,
    offset,
  })

  const buildPageUrl = (nextOffset: number) => {
    const qs = new URLSearchParams()
    if (sp.q) qs.set('q', sp.q)
    if (sp.status) qs.set('status', sp.status)
    if (sp.plan) qs.set('plan', sp.plan)
    qs.set('limit', String(limit))
    qs.set('offset', String(nextOffset))
    return `/admin/users?${qs.toString()}`
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operator"
        title="Users"
        description="Search, filter, and manage every account in the system."
      />

      <form className="grid grid-cols-1 gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[1fr_180px_140px_auto]">
        <input
          type="search"
          name="q"
          defaultValue={sp.q ?? ''}
          placeholder="Search email…"
          className="rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        />
        <select
          name="status"
          defaultValue={sp.status ?? ''}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <input
          type="text"
          name="plan"
          defaultValue={sp.plan ?? ''}
          placeholder="Plan code"
          className="rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        />
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Filter
        </button>
      </form>

      {!data ? (
        <p className="text-sm text-muted-foreground">User list is temporarily unavailable.</p>
      ) : (
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-6 py-3 text-xs text-muted-foreground">
            <span>
              Showing {data.items.length === 0 ? 0 : offset + 1}–
              {offset + data.items.length} of {formatNumber(data.total)}
            </span>
            <span className="font-mono">
              limit {limit} · offset {offset}
            </span>
          </div>

          {data.items.length === 0 ? (
            <p className="px-6 py-12 text-center text-sm text-muted-foreground">
              No users match the current filter.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 font-medium">Email</th>
                  <th className="px-6 py-3 font-medium">Status</th>
                  <th className="px-6 py-3 font-medium">Plan</th>
                  <th className="px-6 py-3 font-medium">Today</th>
                  <th className="px-6 py-3 font-medium">Last query</th>
                  <th className="px-6 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.user_id} className="border-t border-border hover:bg-muted/40">
                    <td className="px-6 py-3">
                      <Link
                        href={`/admin/users/${u.user_id}`}
                        className="text-primary hover:underline"
                      >
                        {u.email}
                      </Link>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {u.user_id.slice(0, 8)}…
                      </p>
                    </td>
                    <td className="px-6 py-3">
                      <span
                        className={`inline-flex h-5 items-center rounded-full border px-2 font-mono text-[10px] uppercase tracking-[0.14em] ${STATUS_BADGE[u.account_status]}`}
                      >
                        {u.account_status}
                      </span>
                      {u.onboarding_status !== 'setup_complete' && (
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          {u.onboarding_status}
                        </p>
                      )}
                    </td>
                    <td className="px-6 py-3 font-mono text-xs">{u.plan_code}</td>
                    <td className="px-6 py-3 tabular-nums">
                      {formatNumber(u.daily_query_count)}
                    </td>
                    <td className="px-6 py-3 text-muted-foreground">
                      {formatRelativeTime(u.last_query_at)}
                    </td>
                    <td className="px-6 py-3 text-muted-foreground">
                      {formatDateTime(u.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="flex items-center justify-between border-t border-border px-6 py-3 text-xs">
            <div>
              {offset > 0 ? (
                <Link
                  href={buildPageUrl(Math.max(0, offset - limit))}
                  className="font-medium text-primary hover:underline"
                >
                  ← Previous
                </Link>
              ) : (
                <span className="text-muted-foreground">← Previous</span>
              )}
            </div>
            <div>
              {offset + data.items.length < data.total ? (
                <Link
                  href={buildPageUrl(offset + limit)}
                  className="font-medium text-primary hover:underline"
                >
                  Next →
                </Link>
              ) : (
                <span className="text-muted-foreground">Next →</span>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
