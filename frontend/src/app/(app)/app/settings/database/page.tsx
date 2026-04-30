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
        eyebrow="Settings"
        title="Database connection"
        description="Review the active database and update credentials if your host, username, or password changes."
      />

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Server className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">Current connection</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                PlainQuery stores the encrypted URL, not the raw value shown here.
              </p>
            </div>
          </div>

          {meta ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-2xl bg-background p-4 ring-1 ring-border">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-semibold">{meta.name}</p>
                    {meta.database_name && (
                      <p className="mt-1 text-sm text-muted-foreground">
                        {meta.db_type ?? 'Database'}: {meta.database_name}
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
                <p className="text-sm text-muted-foreground">
                  Last validated:{' '}
                  {new Date(meta.last_validated_at).toLocaleString([], {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  })}
                </p>
              )}
            </div>
          ) : (
            <div className="mt-6 rounded-2xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
              Connection details are unavailable. Reconnect the database to refresh this state.
            </div>
          )}
        </section>

        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="mb-6 flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Database className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">Update connection</h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Reconnect to a different database or rotate credentials.
              </p>
            </div>
          </div>
          <DatabaseSettingsForm />
        </section>
      </div>

      <div className="rounded-3xl bg-card p-5 shadow-sm ring-1 ring-border">
        <div className="flex items-start gap-3">
          <LockKeyhole className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <p className="text-sm leading-6 text-muted-foreground">
            Updating this connection invalidates cached database pipeline state so future
            MCP questions use the new database credentials.
          </p>
        </div>
      </div>
    </div>
  )
}
