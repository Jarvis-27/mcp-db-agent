import Link from 'next/link'
import { PageHeader } from '@/components/page-header'
import { getAdminQueries } from '@/lib/api/admin'
import { formatDuration, formatNumber, formatRelativeTime } from '@/lib/admin-format'

type SearchParams = {
  user_id?: string
  success?: string
  error_code?: string
  since?: string
  limit?: string
  offset?: string
}

export default async function AdminQueriesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>
}) {
  const sp = await searchParams
  const limit = Math.min(100, Math.max(1, parseInt(sp.limit ?? '25', 10) || 25))
  const offset = Math.max(0, parseInt(sp.offset ?? '0', 10) || 0)
  const success =
    sp.success === 'true' ? 'true' : sp.success === 'false' ? 'false' : undefined

  const data = await getAdminQueries({
    user_id: sp.user_id,
    success,
    error_code: sp.error_code,
    since: sp.since,
    limit,
    offset,
  })

  const buildPageUrl = (nextOffset: number) => {
    const qs = new URLSearchParams()
    if (sp.user_id) qs.set('user_id', sp.user_id)
    if (sp.success) qs.set('success', sp.success)
    if (sp.error_code) qs.set('error_code', sp.error_code)
    if (sp.since) qs.set('since', sp.since)
    qs.set('limit', String(limit))
    qs.set('offset', String(nextOffset))
    return `/admin/queries?${qs.toString()}`
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operator"
        title="Queries"
        description="Cross-user query log. Filterable, paginated, raw SQL inspectable."
      />

      <form className="grid grid-cols-1 gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[1fr_160px_160px_220px_auto]">
        <input
          type="text"
          name="user_id"
          defaultValue={sp.user_id ?? ''}
          placeholder="User ID"
          className="rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        />
        <select
          name="success"
          defaultValue={sp.success ?? ''}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        >
          <option value="">Any outcome</option>
          <option value="true">Success</option>
          <option value="false">Failed</option>
        </select>
        <input
          type="text"
          name="error_code"
          defaultValue={sp.error_code ?? ''}
          placeholder="Error code"
          className="rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        />
        <input
          type="text"
          name="since"
          defaultValue={sp.since ?? ''}
          placeholder="Since (ISO timestamp)"
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
        <p className="text-sm text-muted-foreground">Query log is temporarily unavailable.</p>
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
              No queries match the current filter.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 font-medium">When</th>
                  <th className="px-6 py-3 font-medium">User</th>
                  <th className="px-6 py-3 font-medium">Question / SQL</th>
                  <th className="px-6 py-3 font-medium">Duration</th>
                  <th className="px-6 py-3 font-medium">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((q) => (
                  <tr key={q.id} className="border-t border-border align-top">
                    <td className="px-6 py-3 text-muted-foreground">
                      {formatRelativeTime(q.timestamp)}
                    </td>
                    <td className="px-6 py-3">
                      <Link
                        href={`/admin/users/${q.user_id}`}
                        className="text-primary hover:underline"
                      >
                        {q.user_email ?? q.user_id.slice(0, 8) + '…'}
                      </Link>
                    </td>
                    <td className="px-6 py-3">
                      <p className="max-w-md truncate font-medium">{q.question}</p>
                      {q.sql && (
                        <details className="mt-1 text-xs text-muted-foreground">
                          <summary className="cursor-pointer select-none hover:text-foreground">
                            Show SQL
                          </summary>
                          <pre className="mt-2 max-w-2xl overflow-x-auto rounded-md bg-muted/60 p-3 font-mono text-[11px] leading-5 text-foreground/90">
                            {q.sql}
                          </pre>
                        </details>
                      )}
                      {q.error && (
                        <p className="mt-1 max-w-md truncate text-[11px] text-destructive">
                          {q.error_code ? `${q.error_code}: ` : ''}
                          {q.error}
                        </p>
                      )}
                    </td>
                    <td className="px-6 py-3 font-mono text-xs">
                      {formatDuration(q.duration_ms)}
                    </td>
                    <td className="px-6 py-3">
                      {q.success ? (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700">
                          ok · {formatNumber(q.row_count ?? 0)} rows
                        </span>
                      ) : (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-destructive">
                          failed
                        </span>
                      )}
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
