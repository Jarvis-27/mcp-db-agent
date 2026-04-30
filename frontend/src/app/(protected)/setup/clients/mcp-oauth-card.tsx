'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { Link2, ShieldCheck, Unlink } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/status-badge'
import { startMcpOauthLinkAction, unlinkMcpOauthLinkAction } from '@/lib/api/mcp-oauth'
import type { OAuthLinkStatusResponse } from '@/types/api'

interface Props {
  authMode: 'api_key_only' | 'hybrid' | 'oauth_only'
  oauthEnabledForMcp: boolean
  oauthLinkEnabled: boolean
  apiKeysEnabledForMcp: boolean
  linkStatus: OAuthLinkStatusResponse
  oauthResult?: 'linked' | null
  oauthError?: string | null
  returnPath?: string
}

const OAUTH_ERROR_COPY: Record<string, string> = {
  identity_conflict: 'That OAuth identity is already linked to a different account.',
  invalid_state: 'The OAuth callback state was invalid or expired. Start the link flow again.',
  oauth_not_configured: 'OAuth account linking is not configured on this deployment.',
  token_exchange_failed: 'The OAuth provider token exchange failed. Try the link flow again.',
  token_invalid:
    'The returned OAuth token could not be verified. Try again or check provider configuration.',
}

export function McpOauthCard({
  authMode,
  oauthEnabledForMcp,
  oauthLinkEnabled,
  apiKeysEnabledForMcp,
  linkStatus,
  oauthResult = null,
  oauthError = null,
  returnPath = '/app/setup/clients',
}: Props) {
  const router = useRouter()
  const [error, setError] = useState<string | null>(
    oauthError ? (OAUTH_ERROR_COPY[oauthError] ?? 'OAuth linking failed.') : null,
  )
  const [isStarting, startTransition] = useTransition()
  const [isUnlinking, startUnlinkTransition] = useTransition()

  function handleStart() {
    setError(null)
    startTransition(async () => {
      const result = await startMcpOauthLinkAction()
      if (!result.ok) {
        if (result.redirectTo) {
          router.push(result.redirectTo)
          return
        }
        setError(result.error)
        return
      }
      window.location.href = result.authorizationUrl
    })
  }

  function handleUnlink() {
    setError(null)
    startUnlinkTransition(async () => {
      const result = await unlinkMcpOauthLinkAction()
      if (!result.ok) {
        if (result.redirectTo) {
          router.push(result.redirectTo)
          return
        }
        setError(result.error)
        return
      }
      router.replace(returnPath)
      router.refresh()
    })
  }

  return (
    <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">OAuth access</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Best for remote clients that can complete the MCP OAuth flow.
              </p>
            </div>
          </div>
        </div>
        <StatusBadge
          variant={linkStatus.linked ? 'connected' : oauthEnabledForMcp ? 'warning' : 'inactive'}
          label={linkStatus.linked ? 'Linked' : oauthEnabledForMcp ? 'Not linked' : 'API keys only'}
        />
      </div>

      <div className="mt-5 space-y-4">
        {oauthResult === 'linked' && (
          <Alert>
            <AlertTitle>OAuth account linked</AlertTitle>
            <AlertDescription>Your MCP OAuth identity is now connected to this account.</AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!oauthEnabledForMcp && (
          <Alert>
            <AlertTitle>API-key MCP access is active</AlertTitle>
            <AlertDescription>
              {authMode === 'api_key_only'
                ? 'This deployment is currently accepting API-key MCP auth. ChatGPT requires OAuth before it can connect directly.'
                : 'OAuth is not fully configured for the public MCP endpoint yet.'}
            </AlertDescription>
          </Alert>
        )}

        {oauthEnabledForMcp && !oauthLinkEnabled && (
          <Alert variant="destructive">
            <AlertTitle>Linking flow unavailable</AlertTitle>
            <AlertDescription>
              OAuth is active on the MCP endpoint, but web-app account linking is not configured.
            </AlertDescription>
          </Alert>
        )}

        {oauthEnabledForMcp && (
          <>
            <div className="rounded-2xl bg-background p-4 ring-1 ring-border">
              <p className="font-medium">
                {linkStatus.linked ? 'Linked OAuth identity' : 'No OAuth identity linked yet'}
              </p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {linkStatus.linked
                  ? linkStatus.oauth_email ?? linkStatus.issuer ?? 'Linked without an email claim.'
                  : 'Complete this once before connecting ChatGPT or another OAuth-capable MCP client.'}
              </p>
              {linkStatus.linked && linkStatus.oauth_last_login_at && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Last OAuth MCP use: {new Date(linkStatus.oauth_last_login_at).toLocaleString()}
                </p>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              {!linkStatus.linked && (
                <Button
                  type="button"
                  className="h-10"
                  disabled={!oauthLinkEnabled || isStarting}
                  onClick={handleStart}
                >
                  <Link2 className="h-4 w-4" />
                  {isStarting ? 'Redirecting...' : 'Connect MCP account'}
                </Button>
              )}
              {linkStatus.linked && (
                <Button
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={isUnlinking}
                  onClick={handleUnlink}
                >
                  <Unlink className="h-4 w-4" />
                  {isUnlinking ? 'Unlinking...' : 'Unlink OAuth identity'}
                </Button>
              )}
            </div>

            {apiKeysEnabledForMcp && (
              <p className="text-sm leading-6 text-muted-foreground">
                API keys remain available during rollout, but OAuth is the preferred path
                for remote clients that support it.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
