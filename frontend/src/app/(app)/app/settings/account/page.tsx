import { redirect } from 'next/navigation'
import { Globe2, ShieldCheck } from 'lucide-react'
import { backendFetch } from '@/lib/api/backend'
import { PageHeader } from '@/components/page-header'
import type { AccountResponse } from '@/types/api'
import { TimezoneForm } from './timezone-form'

export default async function AccountSettingsPage() {
  const res = await backendFetch('/v1/account', { cache: 'no-store' })
  if (res.status === 401) redirect('/login')
  if (!res.ok) redirect('/setup/status')

  const account: AccountResponse = await res.json()

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="settings / account"
        title="Account preferences"
        description="Control how your account behaves day to day, including when your daily question quota rolls over."
      />

      <section className="rounded-xl border border-border bg-card shadow-sm">
        <div className="flex items-start gap-4 border-b border-border px-6 py-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Globe2 className="h-4 w-4" />
          </span>
          <div>
            <p className="eyebrow text-primary">time zone</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              Daily quota window
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Your 25-question free quota (or 500 on Pro) resets at midnight in
              this time zone. We detect it from your browser at sign-in, but you
              can pin it explicitly here.
            </p>
          </div>
        </div>
        <div className="px-6 py-5">
          <TimezoneForm currentTimezone={account.timezone || 'UTC'} />
        </div>
      </section>

      <div className="rounded-xl border border-border bg-muted/30 p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
          <p className="text-sm leading-6 text-muted-foreground">
            Changing the time zone recomputes the next reset boundary. It does
            not retroactively change how earlier queries were counted.
          </p>
        </div>
      </div>
    </div>
  )
}
