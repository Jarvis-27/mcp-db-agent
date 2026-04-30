'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { type FormEvent, useState, useTransition } from 'react'
import { AlertTriangle, CheckCircle2, KeyRound, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CopyButton } from '@/components/copy-button'
import { EmptyState } from '@/components/empty-state'
import { createApiKeyAction, revokeApiKeyAction } from '@/lib/api/api-keys'
import type { ApiKeyResponse, CreatedApiKeyResponse } from '@/types/api'
import type { ReturnToRoute } from '@/lib/return-to'

interface ApiKeyManagerProps {
  initialKeys: ApiKeyResponse[]
  mode: 'manage' | 'onboarding'
  returnTo?: ReturnToRoute | null
}

export function ApiKeyManager({ initialKeys, mode, returnTo = null }: ApiKeyManagerProps) {
  const router = useRouter()
  const [keys, setKeys] = useState(initialKeys)
  const [keyName, setKeyName] = useState('default')
  const [error, setError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [revealedKey, setRevealedKey] = useState<CreatedApiKeyResponse | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [isCreating, startCreateTransition] = useTransition()
  const [isRevoking, startRevokeTransition] = useTransition()

  const activeKeys = keys.filter((key) => key.revoked_at === null)
  const revokedKeys = keys.filter((key) => key.revoked_at !== null)
  const isBusy = isCreating || isRevoking

  function handleCreateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    startCreateTransition(async () => {
      const result = await createApiKeyAction(keyName)

      if (!result.ok) {
        if (result.redirectTo) {
          router.push(result.redirectTo)
          return
        }
        setError(result.error)
        return
      }

      setKeys((current) => [result.key, ...current])
      setRevealedKey(result.key)
      setConfirmed(false)
      setKeyName('default')
    })
  }

  function handleRevoke(apiKeyId: string) {
    setError(null)
    setRevokingId(apiKeyId)

    startRevokeTransition(async () => {
      const result = await revokeApiKeyAction(apiKeyId)

      if (!result.ok) {
        setRevokingId(null)
        if (result.redirectTo) {
          router.push(result.redirectTo)
          return
        }
        setError(result.error)
        return
      }

      setKeys((current) =>
        current.map((key) =>
          key.id === apiKeyId ? { ...key, revoked_at: new Date().toISOString() } : key,
        ),
      )
      setRevokingId(null)
    })
  }

  function handleContinue() {
    if (returnTo) {
      router.push(returnTo)
      return
    }

    if (mode === 'onboarding') {
      router.push('/app/setup/clients')
      return
    }

    setRevealedKey(null)
    setConfirmed(false)
  }

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {revealedKey ? (
        <Card className="rounded-3xl border-amber-200 bg-amber-50 shadow-sm">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-background text-amber-700 ring-1 ring-amber-200">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">Save this API key now</CardTitle>
            <CardDescription className="text-base leading-7">
              Raw API keys are shown once. Copy it before leaving this screen.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <Alert className="border-amber-300 bg-background/80">
              <AlertTitle>One-time reveal</AlertTitle>
              <AlertDescription>
                You can revoke this key later, but you cannot reveal this exact raw value again.
              </AlertDescription>
            </Alert>

            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                API key - {revealedKey.name}
              </Label>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 rounded-2xl border bg-background px-3 py-2 text-sm font-mono break-all">
                  {revealedKey.api_key}
                </code>
                <CopyButton text={revealedKey.api_key} onCopied={() => setConfirmed(true)} />
              </div>
            </div>

            <label className="flex cursor-pointer items-center gap-3 rounded-2xl bg-background p-3 text-sm ring-1 ring-border">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="h-4 w-4 rounded border"
              />
              I copied and saved this key somewhere safe.
            </label>

            <Button className="h-11 w-full" disabled={!confirmed} onClick={handleContinue}>
              {returnTo ? 'Return to setup' : mode === 'onboarding' ? 'Continue to client setup' : 'Back to API keys'}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="rounded-3xl shadow-sm">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <KeyRound className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">
              {mode === 'onboarding' ? 'Create your first API key' : 'Create API key'}
            </CardTitle>
            <CardDescription className="text-base leading-7">
              {mode === 'onboarding'
                ? 'Some clients use API keys to authenticate. The free plan allows one active key.'
                : 'Create and revoke the credentials your MCP clients use to authenticate.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateSubmit} className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <div className="space-y-2">
                <Label htmlFor="name">Key name</Label>
                <Input
                  id="name"
                  name="name"
                  type="text"
                  value={keyName}
                  onChange={(event) => setKeyName(event.target.value)}
                  placeholder="default"
                  maxLength={100}
                  className="h-11"
                />
              </div>

              <Button type="submit" className="h-11 self-end" disabled={isBusy}>
                <Plus className="h-4 w-4" />
                {isCreating ? 'Creating...' : 'Create key'}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card className="rounded-3xl shadow-sm">
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="text-2xl">Active keys</CardTitle>
              <CardDescription className="text-base leading-7">
                Revoke keys you no longer use. Revoked keys cannot authenticate.
              </CardDescription>
            </div>
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700 ring-1 ring-emerald-200">
              {activeKeys.length} active
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {activeKeys.length === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No active API keys"
              description="Create a key when a client or integration needs API-key authentication."
            />
          ) : (
            activeKeys.map((key) => (
              <div key={key.id} className="rounded-2xl border bg-background p-4">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold">{key.name}</p>
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        Active
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">{key.prefix}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Created {new Date(key.created_at).toLocaleString()}
                      {key.last_used_at ? ` - Last used ${new Date(key.last_used_at).toLocaleString()}` : ''}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-10"
                    disabled={isBusy}
                    onClick={() => handleRevoke(key.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                    {isRevoking && revokingId === key.id ? 'Revoking...' : 'Revoke'}
                  </Button>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {revokedKeys.length > 0 && (
        <Card className="rounded-3xl shadow-sm">
          <CardHeader>
            <CardTitle className="text-2xl">Revoked keys</CardTitle>
            <CardDescription>These keys are inactive and shown for audit context.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {revokedKeys.map((key) => (
              <div key={key.id} className="rounded-2xl border bg-background p-4">
                <p className="font-semibold">{key.name}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">{key.prefix}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Revoked {key.revoked_at ? new Date(key.revoked_at).toLocaleString() : 'just now'}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {mode === 'manage' && !returnTo && (
        <p className="text-sm text-muted-foreground">
          Need to connect a client?{' '}
          <Link href="/app/setup/clients" className="font-medium text-primary underline-offset-4 hover:underline">
            Open client setup
          </Link>
          .
        </p>
      )}

      <div className="rounded-3xl bg-card p-5 shadow-sm ring-1 ring-border">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <p className="text-sm leading-6 text-muted-foreground">
            Prefer OAuth for clients that support it. Keep API keys for rollout,
            fallback, and integrations that only accept bearer headers.
          </p>
        </div>
      </div>
    </div>
  )
}
