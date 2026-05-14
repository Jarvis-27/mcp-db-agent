'use client'

import { useActionState, useEffect, useState } from 'react'
import {
  Cable,
  Database,
  KeyRound,
  Link2,
  LockKeyhole,
  ShieldCheck,
  TestTube2,
} from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/page-header'
import { CodeBlockWithCopy } from '@/components/code-block-with-copy'
import { FirewallHint } from '@/components/firewall-hint'
import { cn } from '@/lib/utils'
import { getStaticOutboundIpAction, submitDatabaseAction } from './actions'

type State = { error?: string; errorCode?: string } | null
type ConnectionMethod = 'guided' | 'url'

const providers = [
  { value: 'generic_postgres', label: 'PostgreSQL' },
  { value: 'supabase', label: 'Supabase (pooler recommended)' },
  { value: 'neon', label: 'Neon' },
  { value: 'aws_rds', label: 'AWS RDS / Aurora' },
  { value: 'railway', label: 'Railway' },
  { value: 'render', label: 'Render' },
]

const readonlySql = `CREATE ROLE plainquery_reader LOGIN PASSWORD 'use-a-generated-password';
GRANT CONNECT ON DATABASE your_database TO plainquery_reader;
GRANT USAGE ON SCHEMA public TO plainquery_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO plainquery_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO plainquery_reader;`

const methodOptions = [
  {
    id: 'guided' as const,
    icon: Cable,
    title: 'Guided setup',
    description: 'Choose your provider and enter the fields your database dashboard shows.',
  },
  {
    id: 'url' as const,
    icon: Link2,
    title: 'Connection string',
    description: 'Paste a complete URL if your technical team already gave you one.',
  },
]

const hints = [
  {
    icon: Database,
    title: 'Use a read-only user',
    description:
      'PlainQuery blocks write SQL, and a read-only database login adds a separate database-level guardrail.',
  },
  {
    icon: TestTube2,
    title: 'We test before saving',
    description:
      'The backend performs a live SELECT 1 check before storing the encrypted credential.',
  },
  {
    icon: LockKeyhole,
    title: 'Passwords stay encrypted',
    description:
      'The final connection credential is encrypted at rest and never returned to the browser.',
  },
]

export default function SetupDatabasePage() {
  const [method, setMethod] = useState<ConnectionMethod>('guided')
  const [provider, setProvider] = useState('generic_postgres')
  const [staticOutboundIp, setStaticOutboundIp] = useState<string | null>(null)
  const [state, formAction, isPending] = useActionState<State, FormData>(
    submitDatabaseAction,
    null,
  )

  useEffect(() => {
    let cancelled = false
    getStaticOutboundIpAction().then((ip) => {
      if (!cancelled) setStaticOutboundIp(ip)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="setup / database"
        title="Connect the database people want to ask questions about."
        description="Use guided setup for PostgreSQL providers, or paste a full connection string if you already have one."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <section className="rounded-lg border border-border bg-card shadow-sm">
          <div className="border-b border-border px-6 py-4">
            <p className="eyebrow text-primary">connection</p>
            <h2 className="mt-1 font-display text-lg font-semibold">
              Choose how to connect
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Guided setup is the easiest path. Connection strings remain available for
              quick technical handoff.
            </p>
          </div>

          <form action={formAction} className="space-y-6 px-6 py-6">
            <input type="hidden" name="connection_method" value={method} />

            {state?.error && (
              <Alert variant="destructive">
                <AlertDescription>{state.error}</AlertDescription>
                {state.errorCode === 'network_unreachable' && (
                  <FirewallHint
                    staticOutboundIp={staticOutboundIp}
                    variant="error"
                  />
                )}
              </Alert>
            )}

            <FirewallHint staticOutboundIp={staticOutboundIp} variant="form" />

            <div className="grid gap-3 md:grid-cols-2">
              {methodOptions.map((option) => {
                const Icon = option.icon
                const active = method === option.id
                return (
                  <button
                    key={option.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setMethod(option.id)}
                    className={cn(
                      'flex min-h-28 items-start gap-4 rounded-lg border p-4 text-left transition-colors',
                      active
                        ? 'border-primary bg-primary/5 text-foreground ring-1 ring-primary/20'
                        : 'border-border bg-background hover:border-primary/40',
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-9 w-9 shrink-0 items-center justify-center rounded-md',
                        active ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground',
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold">{option.title}</span>
                      <span className="mt-1 block text-sm leading-6 text-muted-foreground">
                        {option.description}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>

            {method === 'guided' ? (
              <div className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="provider" className="text-xs font-medium">
                      Provider
                    </Label>
                    <select
                      id="provider"
                      name="provider"
                      value={provider}
                      onChange={(event) => setProvider(event.target.value)}
                      className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-xs outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    >
                      {providers.map((provider) => (
                        <option key={provider.value} value={provider.value}>
                          {provider.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="sslmode" className="text-xs font-medium">
                      SSL mode
                    </Label>
                    <select
                      id="sslmode"
                      name="sslmode"
                      defaultValue="require"
                      className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-xs outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    >
                      <option value="require">Require SSL</option>
                      <option value="verify-ca">Verify certificate authority</option>
                      <option value="verify-full">Verify full certificate</option>
                    </select>
                  </div>
                </div>

                {provider === 'supabase' && (
                  <Alert className="border-sky-200/80 bg-sky-50/70 text-sky-950">
                    <Database className="h-4 w-4" />
                    <AlertDescription>
                      For Supabase, use the Session Pooler details from Connect /
                      ORMs. The host usually ends with pooler.supabase.com, port is
                      5432, and the user looks like postgres.&lt;project-ref&gt;.
                      Direct db.&lt;project-ref&gt;.supabase.co hosts are IPv6-only
                      by default.
                    </AlertDescription>
                  </Alert>
                )}

                <div className="grid gap-4 md:grid-cols-[1fr_8rem]">
                  <div className="space-y-2">
                    <Label htmlFor="host" className="text-xs font-medium">
                      Host
                    </Label>
                    <Input
                      id="host"
                      name="host"
                      type="text"
                      placeholder={
                        provider === 'supabase'
                          ? 'aws-0-region.pooler.supabase.com'
                          : 'db.example.com'
                      }
                      required
                      className="h-11 font-mono text-[13px]"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="port" className="text-xs font-medium">
                      Port
                    </Label>
                    <Input
                      id="port"
                      name="port"
                      type="number"
                      min={1}
                      max={65535}
                      defaultValue={5432}
                      required
                      className="h-11 font-mono text-[13px]"
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="database" className="text-xs font-medium">
                      Database name
                    </Label>
                    <Input
                      id="database"
                      name="database"
                      type="text"
                      placeholder="analytics"
                      required
                      className="h-11 font-mono text-[13px]"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="username" className="text-xs font-medium">
                      Username
                    </Label>
                    <Input
                      id="username"
                      name="username"
                      type="text"
                      placeholder="plainquery_reader"
                      required
                      className="h-11 font-mono text-[13px]"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password" className="text-xs font-medium">
                    Password
                  </Label>
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    placeholder="Use the read-only user's password"
                    required
                    className="h-11 font-mono text-[13px]"
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                <Alert className="border-amber-200/80 bg-amber-50/70 text-amber-950">
                  <KeyRound className="h-4 w-4" />
                  <AlertDescription>
                    Connection strings usually include the database password. Use a
                    dedicated read-only user, SSL, and IP allowlisting when possible.
                  </AlertDescription>
                </Alert>

                <div className="space-y-2">
                  <Label htmlFor="database_url" className="text-xs font-medium">
                    Database URL
                  </Label>
                  <Input
                    id="database_url"
                    name="database_url"
                    type="text"
                    placeholder="postgresql://user:password@host:5432/dbname?sslmode=require"
                    required
                    className="h-11 font-mono text-[13px]"
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    PostgreSQL and MySQL URLs are supported here. Hosted setup does not
                    accept SQLite database files.
                  </p>
                </div>
              </div>
            )}

            <Button type="submit" className="h-11" disabled={isPending}>
              {isPending ? 'Testing connection...' : 'Test and connect database'}
            </Button>
          </form>
        </section>

        <aside className="space-y-3">
          {hints.map((hint, i) => (
            <div key={hint.title} className="rounded-lg border border-border bg-card p-5 shadow-sm">
              <div className="flex items-start gap-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <hint.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="eyebrow text-muted-foreground">
                    note / {String(i + 1).padStart(2, '0')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold">{hint.title}</h3>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    {hint.description}
                  </p>
                </div>
              </div>
            </div>
          ))}

          <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-700" />
              <h3 className="text-sm font-semibold">Read-only Postgres role</h3>
            </div>
            <CodeBlockWithCopy code={readonlySql} label="postgres" />
          </div>
        </aside>
      </div>
    </div>
  )
}
