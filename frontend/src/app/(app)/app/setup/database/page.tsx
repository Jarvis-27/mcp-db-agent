'use client'

import { useActionState } from 'react'
import { Database, LockKeyhole, ShieldCheck, TestTube2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/page-header'
import { submitDatabaseAction } from './actions'

type State = { error?: string } | null

const hints = [
  {
    icon: Database,
    title: 'Use a read-only database user',
    description:
      'PlainQuery validates SQL as read-only, and a read-only credential adds another guardrail.',
  },
  {
    icon: TestTube2,
    title: 'We test the connection',
    description:
      'The backend performs a live SELECT 1 check before storing the encrypted URL.',
  },
  {
    icon: LockKeyhole,
    title: 'Credentials stay encrypted',
    description:
      'The connection string is encrypted at rest and never returned to the browser.',
  },
]

export default function SetupDatabasePage() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    submitDatabaseAction,
    null,
  )

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="§ setup · database"
        title="Connect the database people want to ask questions about."
        description="Paste a PostgreSQL or MySQL connection string. PlainQuery validates the host, tests connectivity, and stores the credential encrypted."
      />

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="border-b border-border px-6 py-4">
            <p className="eyebrow text-primary">connection</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              Connection string
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              If you&apos;re not sure where to find this, check your provider&apos;s
              connection settings and choose a URL format.
            </p>
          </div>

          <form action={formAction} className="space-y-5 px-6 py-6">
            {state?.error && (
              <Alert variant="destructive">
                <AlertDescription>{state.error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label
                htmlFor="database_url"
                className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground"
              >
                Database URL
              </Label>
              <Input
                id="database_url"
                name="database_url"
                type="text"
                placeholder="postgresql://user:password@host:5432/dbname"
                required
                className="h-11 font-mono text-[13px]"
              />
              <p className="text-xs leading-5 text-muted-foreground">
                Supports{' '}
                <code className="font-mono text-[11px] text-foreground">postgresql://</code>{' '}
                and{' '}
                <code className="font-mono text-[11px] text-foreground">
                  mysql+pymysql://
                </code>
                . SQLite is not supported in hosted mode.
              </p>
            </div>

            <Button type="submit" className="h-11" disabled={isPending}>
              {isPending ? 'Testing connection…' : 'Test and connect database'}
            </Button>
          </form>
        </section>

        <aside className="space-y-3">
          {hints.map((hint, i) => (
            <div
              key={hint.title}
              className="rounded-xl border border-border bg-card p-5 shadow-sm"
            >
              <div className="flex items-start gap-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <hint.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="eyebrow text-muted-foreground">
                    note · {String(i + 1).padStart(2, '0')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold">{hint.title}</h3>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    {hint.description}
                  </p>
                </div>
              </div>
            </div>
          ))}

          <div className="rounded-xl border border-emerald-200/80 bg-emerald-50/70 p-5 text-emerald-900">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="text-sm leading-6">
                URL safety checks block private IPs, path traversal, unsafe hosts, and
                other server-side request forgery risks before any connection attempt.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
