import Link from 'next/link'
import { backendFetch } from '@/lib/api/backend'
import { getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { redirect } from 'next/navigation'
import { resolveStatusResponseDestination } from '@/lib/onboarding'
import type { SetupPayloadResponse } from '@/types/api'
import { ClientConfigDisplay } from './client-config-display'

export default async function SetupClientsPage() {
  const status = await getOnboardingStatusOrRedirect()
  const destination = resolveStatusResponseDestination(status)

  if (destination !== '/setup/clients') {
    redirect(destination)
  }

  const res = await backendFetch('/v1/account/setup-payloads', {
    method: 'POST',
    body: JSON.stringify({ raw_api_key: null }),
    cache: 'no-store',
  })

  if (res.status === 401) redirect('/login')

  if (res.status === 409) {
    redirect('/setup/status')
  }

  if (!res.ok) {
    return (
      <div className="text-center py-12 text-muted-foreground text-sm">
        Failed to load setup configuration. Please refresh the page.
      </div>
    )
  }

  const payload: SetupPayloadResponse = await res.json()
  const quota = payload.quota_summary
  const clients = payload.clients
  const apiKeyState = payload.api_key_state
  const hasActiveKey = apiKeyState.active_key_count > 0
  const selectedKeyLabel = apiKeyState.selected_api_key_name
    ? `${apiKeyState.selected_api_key_name}${apiKeyState.selected_api_key_prefix ? ` (${apiKeyState.selected_api_key_prefix})` : ''}`
    : apiKeyState.selected_api_key_prefix

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold">You&apos;re all set!</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Copy the configuration below into your MCP client to start querying in
          plain English.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-4 flex flex-wrap gap-6 text-sm">
        <div>
          <p className="text-muted-foreground text-xs mb-0.5">Plan</p>
          <p className="font-medium capitalize">{payload.plan_code}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs mb-0.5">Daily queries</p>
          <p className="font-medium">
            {quota.daily_used} / {quota.daily_limit} used
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs mb-0.5">Remaining</p>
          <p className="font-medium">{quota.daily_remaining}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs mb-0.5">Resets</p>
          <p className="font-medium">
            {new Date(quota.reset_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </p>
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-medium">MCP endpoint</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded-md border bg-muted px-3 py-2 text-sm font-mono truncate">
            {payload.mcp_url}
          </code>
        </div>
      </div>

      <ClientConfigDisplay clients={clients} />

      {payload.sample_prompts.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium">Sample prompts to try</p>
          <ul className="space-y-2">
            {payload.sample_prompts.map((prompt, i) => (
              <li
                key={i}
                className="text-sm text-muted-foreground border rounded-md px-3 py-2 italic"
              >
                &ldquo;{prompt}&rdquo;
              </li>
            ))}
          </ul>
        </div>
      )}

      {!hasActiveKey && (
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/20 px-4 py-3 text-sm">
          <strong>API key required:</strong> No active API key was found.{' '}
          <Link
            href="/api-keys?returnTo=%2Fsetup%2Fclients"
            className="underline underline-offset-4"
          >
            Open API key management
          </Link>{' '}
          to create one, then return to this page.
        </div>
      )}

      {hasActiveKey && apiKeyState.requires_manual_key_entry && (
        <div className="rounded-md border border-sky-300 bg-sky-50 dark:bg-sky-950/20 px-4 py-3 text-sm">
          <strong>Paste your API key when prompted:</strong>{' '}
          {selectedKeyLabel ? (
            <>An active key exists for {selectedKeyLabel}, but raw keys are only shown once.</>
          ) : (
            <>An active key exists for this account, but raw keys are only shown once.</>
          )}{' '}
          The snippets above use placeholders, so copy one of your active keys from when it was
          created or create a new key in{' '}
          <Link
            href="/api-keys?returnTo=%2Fsetup%2Fclients"
            className="underline underline-offset-4"
          >
            API key management
          </Link>
          .
        </div>
      )}
    </div>
  )
}