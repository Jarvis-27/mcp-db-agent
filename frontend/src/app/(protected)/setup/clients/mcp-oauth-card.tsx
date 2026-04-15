'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
      router.replace('/setup/clients')
      router.refresh()
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">OAuth access for remote MCP clients</CardTitle>
        <CardDescription>
          {oauthEnabledForMcp
            ? 'Use this to link your signed-in account to the OAuth identity that ChatGPT, Cursor, and other OAuth-capable MCP clients will use.'
            : 'This deployment is currently exposing API-key MCP access only.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {oauthResult === 'linked' && (
          <Alert>
            <AlertTitle>OAuth account linked</AlertTitle>
            <AlertDescription>
              Your MCP OAuth identity is now connected to this account.
            </AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!oauthEnabledForMcp && (
          <Alert>
            <AlertTitle>API keys only</AlertTitle>
            <AlertDescription>
              {authMode === 'api_key_only'
                ? 'The public /mcp endpoint is not yet accepting OAuth bearer tokens, so ChatGPT remains unavailable and OAuth-capable clients should use the API-key instructions below.'
                : 'OAuth is not fully configured for the public /mcp endpoint yet.'}
            </AlertDescription>
          </Alert>
        )}

        {oauthEnabledForMcp && !oauthLinkEnabled && (
          <Alert variant="destructive">
            <AlertTitle>Linking flow unavailable</AlertTitle>
            <AlertDescription>
              OAuth is active on /mcp, but the web-app linking client is not configured.
              Existing linked accounts can still use OAuth, but new links cannot be created
              from this page.
            </AlertDescription>
          </Alert>
        )}

        {oauthEnabledForMcp && (
          <>
            <div className="rounded-md border bg-muted/40 px-3 py-3 text-sm">
              <p className="font-medium">
                {linkStatus.linked ? 'Linked OAuth identity' : 'No OAuth identity linked yet'}
              </p>
              <p className="mt-1 text-muted-foreground">
                {linkStatus.linked
                  ? linkStatus.oauth_email ?? linkStatus.issuer ?? 'Linked without an email claim.'
                  : 'Complete the link flow once in the web app before connecting ChatGPT or other OAuth-based MCP clients.'}
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
                  disabled={!oauthLinkEnabled || isStarting}
                  onClick={handleStart}
                >
                  {isStarting ? 'Redirecting...' : 'Connect MCP account'}
                </Button>
              )}
              {linkStatus.linked && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={isUnlinking}
                  onClick={handleUnlink}
                >
                  {isUnlinking ? 'Unlinking...' : 'Unlink OAuth identity'}
                </Button>
              )}
            </div>

            {apiKeysEnabledForMcp && (
              <p className="text-xs text-muted-foreground">
                This deployment still accepts API keys on /mcp, but OAuth is the preferred
                path for remote clients that support it.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
