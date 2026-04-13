'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { type FormEvent, useState, useTransition } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CopyButton } from '@/components/copy-button'
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
      router.push('/setup/clients')
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
        <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/20">
          <CardHeader>
            <CardTitle>Save your API key</CardTitle>
            <CardDescription>
              This key is shown exactly once. Copy it now before you continue.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert className="border-amber-400 bg-amber-100 dark:bg-amber-900/30">
              <AlertTitle>Store this key securely</AlertTitle>
              <AlertDescription>
                You will not be able to reveal the raw key again after leaving this view.
              </AlertDescription>
            </Alert>

            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">
                API key - {revealedKey.name}
              </Label>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md border bg-background px-3 py-2 text-sm font-mono break-all">
                  {revealedKey.api_key}
                </code>
                <CopyButton text={revealedKey.api_key} onCopied={() => setConfirmed(true)} />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="confirm-api-key"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="h-4 w-4 rounded border"
              />
              <label htmlFor="confirm-api-key" className="text-sm cursor-pointer">
                I have copied and saved my API key
              </label>
            </div>

            <Button className="w-full" disabled={!confirmed} onClick={handleContinue}>
              {returnTo ? 'Return to setup' : mode === 'onboarding' ? 'Continue to client setup' : 'Back to API keys'}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{mode === 'onboarding' ? 'Create your first API key' : 'Create API key'}</CardTitle>
            <CardDescription>
              {mode === 'onboarding'
                ? 'Your MCP clients use this key to authenticate. The free plan allows one active key.'
                : 'Create, review, and revoke the API keys used by your MCP clients.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="name">Key name</Label>
                <Input
                  id="name"
                  name="name"
                  type="text"
                  value={keyName}
                  onChange={(event) => setKeyName(event.target.value)}
                  placeholder="default"
                  maxLength={100}
                />
              </div>

              <Button type="submit" className="w-full" disabled={isBusy}>
                {isCreating ? 'Creating key...' : 'Create API key'}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Active keys</CardTitle>
          <CardDescription>
            Revoke keys you no longer need. Revoked keys cannot be restored.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {activeKeys.length === 0 ? (
            <p className="text-sm text-muted-foreground">No active API keys yet.</p>
          ) : (
            activeKeys.map((key) => (
              <div key={key.id} className="flex items-center justify-between gap-4 rounded-lg border p-3">
                <div className="space-y-1">
                  <p className="text-sm font-medium">{key.name}</p>
                  <p className="text-xs text-muted-foreground font-mono">{key.prefix}</p>
                  <p className="text-xs text-muted-foreground">
                    Created {new Date(key.created_at).toLocaleString()}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  disabled={isBusy}
                  onClick={() => handleRevoke(key.id)}
                >
                  {isRevoking && revokingId === key.id ? 'Revoking...' : 'Revoke'}
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {revokedKeys.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Revoked keys</CardTitle>
            <CardDescription>These keys are inactive and can no longer authenticate.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {revokedKeys.map((key) => (
              <div key={key.id} className="rounded-lg border p-3">
                <p className="text-sm font-medium">{key.name}</p>
                <p className="text-xs text-muted-foreground font-mono">{key.prefix}</p>
                <p className="text-xs text-muted-foreground">
                  Revoked {key.revoked_at ? new Date(key.revoked_at).toLocaleString() : 'just now'}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {mode === 'manage' && !returnTo && (
        <p className="text-sm text-muted-foreground">
          Need to continue setup instead? Go back to{' '}
          <Link href="/setup/clients" className="underline underline-offset-4">
            client setup
          </Link>
          .
        </p>
      )}
    </div>
  )
}
