'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { type FormEvent, useState, useTransition } from 'react'
import { AlertTriangle, KeyRound, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CopyButton } from '@/components/copy-button'
import { EmptyState } from '@/components/empty-state'
import { StatusBadge } from '@/components/status-badge'
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
    <div className="space-y-5">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {revealedKey ? (
        <section className="rounded-xl border border-amber-300/80 bg-amber-50/70 shadow-sm">
          <div className="flex items-start gap-4 border-b border-amber-200/80 px-6 py-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-card text-amber-700 ring-1 ring-amber-200">
              <AlertTriangle className="h-4 w-4" />
            </span>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-amber-700">
                one-time reveal
              </p>
              <h2 className="mt-1 font-display text-xl font-semibold -tracking-[0.02em] text-amber-950">
                Save this API key now
              </h2>
              <p className="mt-1 text-sm leading-6 text-amber-900/80">
                Raw API keys are shown once. Copy it before leaving this screen.
              </p>
            </div>
          </div>

          <div className="space-y-5 px-6 py-5">
            <Alert className="border-amber-300/80 bg-card">
              <AlertTitle>Heads up</AlertTitle>
              <AlertDescription>
                You can revoke this key later, but you cannot reveal this exact raw value again.
              </AlertDescription>
            </Alert>

            <div className="space-y-2">
              <Label className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                API key · {revealedKey.name}
              </Label>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 rounded-md border border-border bg-card px-3 py-2 font-mono text-[12.5px] break-all">
                  {revealedKey.api_key}
                </code>
                <CopyButton
                  text={revealedKey.api_key}
                  onCopied={() => setConfirmed(true)}
                />
              </div>
            </div>

            <label className="flex cursor-pointer items-center gap-3 rounded-md border border-amber-200/80 bg-card p-3 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="h-4 w-4 rounded border accent-primary"
              />
              I copied and saved this key somewhere safe.
            </label>

            <Button
              className="h-11 w-full justify-between"
              disabled={!confirmed}
              onClick={handleContinue}
            >
              {returnTo
                ? 'Return to setup'
                : mode === 'onboarding'
                  ? 'Continue to client setup'
                  : 'Back to API keys'}
            </Button>
          </div>
        </section>
      ) : (
        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="flex items-start gap-4 border-b border-border px-6 py-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <KeyRound className="h-4 w-4" />
            </span>
            <div>
              <p className="eyebrow text-primary">§ 01 · create</p>
              <h2 className="mt-1 font-display text-xl font-semibold -tracking-[0.02em]">
                {mode === 'onboarding' ? 'Create your first API key' : 'Create API key'}
              </h2>
              <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
                {mode === 'onboarding'
                  ? 'Some clients use API keys to authenticate. The free plan allows one active key.'
                  : 'Create and revoke the credentials your MCP clients use to authenticate.'}
              </p>
            </div>
          </div>

          <form
            onSubmit={handleCreateSubmit}
            className="grid gap-3 px-6 py-5 sm:grid-cols-[1fr_auto] sm:items-end"
          >
            <div className="space-y-2">
              <Label
                htmlFor="name"
                className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
              >
                Key name
              </Label>
              <Input
                id="name"
                name="name"
                type="text"
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder="default"
                maxLength={100}
                className="h-11 font-mono text-[13px]"
              />
            </div>

            <Button type="submit" className="h-11" disabled={isBusy}>
              <Plus className="h-4 w-4" />
              {isCreating ? 'Creating…' : 'Create key'}
            </Button>
          </form>
        </section>
      )}

      <section className="rounded-xl border border-border bg-card shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border px-6 py-4">
          <div>
            <p className="eyebrow text-primary">§ 02 · active</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              Active keys
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Revoke keys you no longer use. Revoked keys cannot authenticate.
            </p>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground tabular-nums">
            {activeKeys.length} active
          </span>
        </div>

        <div className="px-6 py-5">
          {activeKeys.length === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No active API keys"
              description="Create a key when a client or integration needs API-key authentication."
            />
          ) : (
            <ul className="divide-y divide-border">
              {activeKeys.map((key) => (
                <li
                  key={key.id}
                  className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold">{key.name}</p>
                      <StatusBadge variant="connected" label="Active" />
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                      {key.prefix}
                    </p>
                    <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                      created {new Date(key.created_at).toLocaleDateString()}
                      {key.last_used_at
                        ? ` · last used ${new Date(key.last_used_at).toLocaleDateString()}`
                        : ' · never used'}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9"
                    disabled={isBusy}
                    onClick={() => handleRevoke(key.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {isRevoking && revokingId === key.id ? 'Revoking…' : 'Revoke'}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {revokedKeys.length > 0 && (
        <section className="rounded-xl border border-border bg-card shadow-sm">
          <div className="border-b border-border px-6 py-4">
            <p className="eyebrow text-muted-foreground">§ 03 · audit</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              Revoked keys
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              These keys are inactive and shown for audit context.
            </p>
          </div>
          <ul className="divide-y divide-border px-6 py-2">
            {revokedKeys.map((key) => (
              <li key={key.id} className="py-3">
                <p className="text-sm font-semibold">{key.name}</p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  {key.prefix}
                </p>
                <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                  revoked{' '}
                  {key.revoked_at
                    ? new Date(key.revoked_at).toLocaleString()
                    : 'just now'}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mode === 'manage' && !returnTo && (
        <p className="text-sm text-muted-foreground">
          Need to connect a client?{' '}
          <Link
            href="/app/setup/clients"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Open client setup
          </Link>
          .
        </p>
      )}

      <div className="rounded-xl border border-border bg-muted/30 p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
          <p className="text-sm leading-6 text-muted-foreground">
            Prefer OAuth for clients that support it. Keep API keys for rollout, fallback,
            and integrations that only accept bearer headers.
          </p>
        </div>
      </div>
    </div>
  )
}
