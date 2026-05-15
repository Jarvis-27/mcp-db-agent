'use client'

import { useActionState, useEffect, useState } from 'react'
import { Cable, KeyRound, Link2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FirewallHint } from '@/components/firewall-hint'
import { cn } from '@/lib/utils'
import { getStaticOutboundIpAction, updateDatabaseAction } from './actions'

type State = { error?: string; errorCode?: string; success?: boolean } | null
type ConnectionMethod = 'guided' | 'url'

const providers = [
  { value: 'generic_postgres', label: 'PostgreSQL' },
  { value: 'supabase', label: 'Supabase (pooler recommended)' },
  { value: 'neon', label: 'Neon' },
  { value: 'aws_rds', label: 'AWS RDS / Aurora' },
  { value: 'railway', label: 'Railway' },
  { value: 'render', label: 'Render' },
]

const methodOptions = [
  {
    id: 'guided' as const,
    icon: Cable,
    title: 'Guided setup',
    description: 'Update with provider fields instead of hand-writing a URL.',
  },
  {
    id: 'url' as const,
    icon: Link2,
    title: 'Connection string',
    description: 'Paste a complete replacement URL from your database provider.',
  },
]

export function DatabaseSettingsForm() {
  const [method, setMethod] = useState<ConnectionMethod>('guided')
  const [provider, setProvider] = useState('generic_postgres')
  const [staticOutboundIp, setStaticOutboundIp] = useState<string | null>(null)
  const [state, formAction, isPending] = useActionState<State, FormData>(
    updateDatabaseAction,
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
    <form action={formAction} className="space-y-5">
      <input type="hidden" name="connection_method" value={method} />

      {state?.error && (
        <Alert variant="destructive">
          <AlertDescription>{state.error}</AlertDescription>
          {state.errorCode === 'network_unreachable' && (
            <FirewallHint staticOutboundIp={staticOutboundIp} variant="error" />
          )}
        </Alert>
      )}
      {state?.success && (
        <Alert className="border-emerald-200/80 bg-emerald-50/70 text-emerald-900">
          <AlertDescription>Database connection updated successfully.</AlertDescription>
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
                'flex min-h-28 items-start gap-3 rounded-lg border p-4 text-left transition-colors',
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
        <div className="space-y-4">
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
              <KeyRound className="h-4 w-4" />
              <AlertDescription>
                For Supabase, use the Session Pooler details from Connect / ORMs.
                The host usually ends with pooler.supabase.com, port is 5432, and
                the user looks like postgres.&lt;project-ref&gt;. Direct
                db.&lt;project-ref&gt;.supabase.co hosts are IPv6-only by default.
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
              Connection strings usually include the database password. Use a dedicated
              read-only user, SSL, and IP allowlisting when possible.
            </AlertDescription>
          </Alert>

          <div className="space-y-2">
            <Label htmlFor="database_url" className="text-xs font-medium">
              New connection string
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
              PostgreSQL URLs are supported here. The backend validates and
              tests the connection before replacing the stored credential.
            </p>
          </div>
        </div>
      )}

      <Button type="submit" className="h-11" disabled={isPending}>
        {isPending ? 'Testing connection...' : 'Update database'}
      </Button>
    </form>
  )
}
