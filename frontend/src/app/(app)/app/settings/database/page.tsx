import { redirect } from 'next/navigation'
import { Database, LockKeyhole, Server } from 'lucide-react'
import { backendFetch } from '@/lib/api/backend'
import { getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import type { DatabaseMetadataResponse } from '@/types/api'
import { StatusBadge } from '@/components/status-badge'
import { PageHeader } from '@/components/page-header'
import { DatabaseSettingsForm } from './settings-form'

export default async function DatabaseSettingsPage() {
  const status = await getOnboardingStatusOrRedirect()

  if (status.status !== 'setup_complete') {
    if (status.status === 'pending_db_connection') redirect('/app/setup/database')
    else redirect('/setup/status')
  }

  const metaRes = await backendFetch('/v1/account/database', { cache: 'no-store' })
  const meta: DatabaseMetadataResponse | null = metaRes.ok ? await metaRes.json() : null

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="settings / database"
        title="Database connection"
        description="Review the active database and update it with guided provider fields or a replacement connection string."
      />

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="flex items-start gap-4 border-b border-border px-6 py-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Server className="h-4 w-4" />
            </span>
            <div>
              <p className="eyebrow text-primary">current</p>
              <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
                Current connection
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                PlainQuery stores the encrypted credential and only shows a safe summary.
              </p>
            </div>
          </div>

          <div className="px-6 py-5">
            {meta ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-border bg-muted/30 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <p className="font-display text-base font-semibold -tracking-[0.02em]">
                        {meta.name}
                      </p>
                      {meta.database_name && (
                        <p className="mt-1 font-mono text-[12px] text-muted-foreground">
                          {meta.db_type ?? 'database'} / {meta.database_name}
                          {meta.host ? ` @ ${meta.host}` : ''}
                        </p>
                      )}
                    </div>
                    <StatusBadge
                      variant={meta.connected ? 'connected' : 'error'}
                      label={meta.connected ? 'Connected' : 'Error'}
                    />
                  </div>
                </div>
                {meta.last_validated_at && (
                  <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                    last validated /{' '}
                    {new Date(meta.last_validated_at).toLocaleString([], {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </p>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-amber-200/80 bg-amber-50/70 p-4 text-sm text-amber-900">
                Connection details are unavailable. Reconnect the database to refresh
                this state.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="flex items-start gap-4 border-b border-border px-6 py-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Database className="h-4 w-4" />
            </span>
            <div>
              <p className="eyebrow text-primary">update</p>
              <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
                Update connection
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Reconnect to a different database, rotate credentials, or paste a full URL.
              </p>
            </div>
          </div>
          <div className="px-6 py-5">
            <DatabaseSettingsForm />
          </div>
        </section>
      </div>

      <div className="rounded-xl border border-border bg-muted/30 p-5">
        <div className="flex items-start gap-3">
          <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
          <p className="text-sm leading-6 text-muted-foreground">
            Updating this connection invalidates cached database pipeline state so future
            MCP questions use the new database credentials.
          </p>
        </div>
      </div>
    </div>
  )
}
