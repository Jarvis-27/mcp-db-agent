import Link from 'next/link'
import { notFound } from 'next/navigation'
import { AlertTriangle, KeyRound, Power, ShieldOff, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/page-header'
import { getAdminUserDetail } from '@/lib/api/admin'
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  formatRelativeTime,
} from '@/lib/admin-format'
import {
  closeUserAction,
  revokeApiKeyAction,
  suspendUserAction,
  unsuspendUserAction,
} from './actions'
import type { AccountStatus } from '@/types/api'

const STATUS_BADGE: Record<AccountStatus, string> = {
  active: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30',
  suspended: 'bg-amber-500/10 text-amber-700 border-amber-500/30',
  closed: 'bg-red-500/10 text-red-700 border-red-500/30',
}

export default async function AdminUserDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ error?: string }>
}) {
  const { id } = await params
  const { error } = await searchParams

  const user = await getAdminUserDetail(id)
  if (!user) notFound()

  // Bind the user id to each server action so the form does not need a hidden input.
  const suspendBound = suspendUserAction.bind(null, user.user_id)
  const unsuspendBound = unsuspendUserAction.bind(null, user.user_id)
  const closeBound = closeUserAction.bind(null, user.user_id)

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operator · user"
        title={user.email}
        description={`Account ${user.user_id.slice(0, 8)}… created ${formatRelativeTime(user.created_at)}`}
        action={
          <Link
            href="/admin/users"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Back to users
          </Link>
        }
      />

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="eyebrow text-muted-foreground">Account</p>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status</span>
              <span
                className={`inline-flex h-5 items-center rounded-full border px-2 font-mono text-[10px] uppercase tracking-[0.14em] ${STATUS_BADGE[user.account_status]}`}
              >
                {user.account_status}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Onboarding</span>
              <span className="font-mono text-xs">{user.onboarding_status}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Plan</span>
              <span className="font-mono text-xs">{user.plan_code}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Billing</span>
              <span className="font-mono text-xs">{user.billing_status}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Timezone</span>
              <span className="font-mono text-xs">{user.timezone}</span>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <p className="eyebrow text-muted-foreground">Quota</p>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Queries today</span>
              <span className="tabular-nums">{formatNumber(user.daily_query_count)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Resets</span>
              <span className="text-xs">{formatDateTime(user.daily_quota_reset_at)}</span>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <p className="eyebrow text-muted-foreground">Database</p>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Name</span>
              <span className="font-mono text-xs">{user.db_name ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Validation</span>
              <span className="font-mono text-xs">
                {user.db_validation_status ?? '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Last checked</span>
              <span className="text-xs">
                {formatRelativeTime(user.db_last_validation_at)}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-6">
        <h2 className="font-display text-lg font-semibold">Account actions</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Mutations are applied immediately and bust this worker&apos;s session cache.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          {user.account_status === 'active' && (
            <form action={suspendBound} className="contents">
              <details className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-amber-700">
                  <ShieldOff className="h-4 w-4" />
                  Suspend account
                </summary>
                <div className="mt-3 flex flex-col gap-2">
                  <input
                    name="reason"
                    type="text"
                    placeholder="Reason (optional, max 500 chars)"
                    maxLength={500}
                    className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    className="self-start rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
                  >
                    Confirm suspend
                  </button>
                </div>
              </details>
            </form>
          )}

          {user.account_status === 'suspended' && (
            <form action={unsuspendBound}>
              <button
                type="submit"
                className="inline-flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-500/20"
              >
                <Power className="h-4 w-4" /> Unsuspend
              </button>
            </form>
          )}

          {user.account_status !== 'closed' && (
            <form action={closeBound} className="contents">
              <details className="rounded-md border border-destructive/40 bg-destructive/5 p-3">
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-destructive">
                  <Trash2 className="h-4 w-4" />
                  Close account
                </summary>
                <div className="mt-3 flex flex-col gap-2">
                  <p className="text-xs text-muted-foreground">
                    Closing is irreversible. All API keys and sessions are revoked.
                  </p>
                  <button
                    type="submit"
                    className="self-start rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-white hover:bg-destructive/90"
                  >
                    Confirm close
                  </button>
                </div>
              </details>
            </form>
          )}

          {user.account_status === 'closed' && (
            <p className="text-sm text-muted-foreground">
              This account is closed. No further actions available.
            </p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">API keys</h2>
        </div>
        {user.api_keys.length === 0 ? (
          <p className="px-6 py-6 text-sm text-muted-foreground">No API keys.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-6 py-3 font-medium">Name</th>
                <th className="px-6 py-3 font-medium">Prefix</th>
                <th className="px-6 py-3 font-medium">Scopes</th>
                <th className="px-6 py-3 font-medium">Created</th>
                <th className="px-6 py-3 font-medium">Last used</th>
                <th className="px-6 py-3 font-medium">Status</th>
                <th className="px-6 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {user.api_keys.map((k) => {
                const revokeBound = revokeApiKeyAction.bind(null, user.user_id, k.id)
                return (
                  <tr key={k.id} className="border-t border-border align-middle">
                    <td className="px-6 py-3 font-medium">{k.name}</td>
                    <td className="px-6 py-3 font-mono text-xs">{k.prefix}…</td>
                    <td className="px-6 py-3 font-mono text-xs">{k.scopes.join(', ')}</td>
                    <td className="px-6 py-3 text-xs text-muted-foreground">
                      {formatDateTime(k.created_at)}
                    </td>
                    <td className="px-6 py-3 text-xs text-muted-foreground">
                      {formatRelativeTime(k.last_used_at)}
                    </td>
                    <td className="px-6 py-3">
                      {k.revoked_at ? (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                          revoked {formatRelativeTime(k.revoked_at)}
                        </span>
                      ) : (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700">
                          active
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3 text-right">
                      {!k.revoked_at && (
                        <form action={revokeBound}>
                          <button
                            type="submit"
                            className="inline-flex items-center gap-1.5 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/15"
                          >
                            <KeyRound className="h-3 w-3" />
                            Revoke
                          </button>
                        </form>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">Recent queries</h2>
          <Link
            href={`/admin/queries?user_id=${user.user_id}`}
            className="text-xs font-medium text-primary hover:underline"
          >
            View all →
          </Link>
        </div>
        {user.recent_queries.length === 0 ? (
          <p className="px-6 py-6 text-sm text-muted-foreground">No queries yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-6 py-3 font-medium">When</th>
                <th className="px-6 py-3 font-medium">Question</th>
                <th className="px-6 py-3 font-medium">Duration</th>
                <th className="px-6 py-3 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {user.recent_queries.map((q) => (
                <tr key={q.id} className="border-t border-border align-top">
                  <td className="px-6 py-3 text-muted-foreground">
                    {formatRelativeTime(q.timestamp)}
                  </td>
                  <td className="px-6 py-3 max-w-md truncate">{q.question}</td>
                  <td className="px-6 py-3 font-mono text-xs">
                    {formatDuration(q.duration_ms)}
                  </td>
                  <td className="px-6 py-3">
                    {q.success ? (
                      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700">
                        ok · {formatNumber(q.row_count ?? 0)}
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
      </section>
    </div>
  )
}
