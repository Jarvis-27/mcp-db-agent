import Link from 'next/link'
import { redirect } from 'next/navigation'
import { AlertTriangle, ArrowRight, CopyCheck, MessageSquareText, PlugZap } from 'lucide-react'
import { backendFetch } from '@/lib/api/backend'
import { getMcpOauthLinkStatusOrRedirect } from '@/lib/api/mcp-oauth'
import { getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import type { SetupPayloadResponse } from '@/types/api'
import { CodeBlockWithCopy } from '@/components/code-block-with-copy'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ClientConfigPanel } from './client-config-panel'
import { McpOauthCard } from '@/app/(protected)/setup/clients/mcp-oauth-card'

interface Props {
  searchParams: Promise<{ oauth?: string; oauth_error?: string }>
}

export default async function AppSetupClientsPage({ searchParams }: Props) {
  const status = await getOnboardingStatusOrRedirect()

  if (status.status !== 'setup_complete') {
    if (status.status === 'pending_db_connection') redirect('/app/setup/database')
    else redirect('/setup/status')
  }

  const [{ oauth, oauth_error: oauthError }, res, oauthLinkStatus] = await Promise.all([
    searchParams,
    backendFetch('/v1/account/setup-payloads', {
      method: 'POST',
      body: JSON.stringify({ raw_api_key: null }),
      cache: 'no-store',
    }),
    getMcpOauthLinkStatusOrRedirect().catch((error: Error) => {
      if (error.message === 'UNAUTHORIZED') redirect('/login')
      throw error
    }),
  ])

  if (res.status === 401) redirect('/login')
  if (res.status === 409) redirect('/app/setup/database')

  if (!res.ok) {
    return (
      <div className="rounded-3xl bg-card p-8 text-center text-sm text-muted-foreground shadow-sm ring-1 ring-border">
        Failed to load setup configuration. Please refresh the page.
      </div>
    )
  }

  const payload: SetupPayloadResponse = await res.json()
  const hasActiveKey = payload.api_key_state.active_key_count > 0
  const selectedKeyLabel = payload.api_key_state.selected_api_key_name
    ? `${payload.api_key_state.selected_api_key_name}${payload.api_key_state.selected_api_key_prefix ? ` (${payload.api_key_state.selected_api_key_prefix})` : ''}`
    : payload.api_key_state.selected_api_key_prefix

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Client setup"
        title="Connect the place where people will ask questions."
        description="Copy the MCP endpoint and client-specific setup. Once connected, try a simple schema question first."
        action={
          <Link href="/app/usage" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-10')}>
            View usage
            <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      <section className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <PlugZap className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">MCP endpoint</h2>
              <p className="mt-1 text-sm text-muted-foreground">Use this URL in every supported client.</p>
            </div>
          </div>
          <div className="mt-5">
            <CodeBlockWithCopy code={payload.mcp_url} inline />
          </div>
        </div>

        <div className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Auth mode</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The generated instructions adapt to this deployment.
              </p>
            </div>
            <StatusBadge
              variant={payload.oauth_enabled_for_mcp ? 'connected' : hasActiveKey ? 'info' : 'warning'}
              label={payload.oauth_enabled_for_mcp ? 'OAuth available' : hasActiveKey ? 'API key ready' : 'Needs key'}
            />
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <MiniStat label="Plan" value={payload.plan_code} />
            <MiniStat label="Daily quota" value={`${payload.quota_summary.daily_remaining}/${payload.quota_summary.daily_limit} left`} />
            <MiniStat label="API keys" value={`${payload.api_key_state.active_key_count} active`} />
          </div>
        </div>
      </section>

      <McpOauthCard
        authMode={payload.mcp_auth_mode}
        oauthEnabledForMcp={payload.oauth_enabled_for_mcp}
        oauthLinkEnabled={payload.oauth_link_enabled}
        apiKeysEnabledForMcp={payload.api_keys_enabled_for_mcp}
        linkStatus={oauthLinkStatus}
        oauthResult={oauth === 'linked' ? 'linked' : null}
        oauthError={oauthError ?? null}
        returnPath="/app/setup/clients"
      />

      <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
        <div className="mb-5 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <CopyCheck className="h-5 w-5" />
          </span>
          <div>
            <h2 className="text-lg font-semibold">Client instructions</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose the client your team will actually use first.
            </p>
          </div>
        </div>
        <ClientConfigPanel clients={payload.clients} />
      </section>

      {payload.sample_prompts.length > 0 && (
        <section className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <MessageSquareText className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">First questions to try</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Start with safe, simple checks before asking business questions.
              </p>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {payload.sample_prompts.map((prompt) => (
              <span
                key={prompt}
                className="rounded-full border bg-background px-3 py-1.5 text-sm text-muted-foreground"
              >
                &quot;{prompt}&quot;
              </span>
            ))}
          </div>
        </section>
      )}

      {!hasActiveKey && payload.mcp_auth_mode === 'api_key_only' && (
        <WarningPanel>
          API-key auth is required for this deployment.{' '}
          <Link href="/app/api-keys" className="font-semibold underline underline-offset-4">
            Create an API key
          </Link>{' '}
          and return to client setup.
        </WarningPanel>
      )}

      {hasActiveKey && payload.api_key_state.requires_manual_key_entry && payload.mcp_auth_mode === 'api_key_only' && (
        <WarningPanel>
          {selectedKeyLabel
            ? `An active key exists for ${selectedKeyLabel}, but raw keys are only shown once.`
            : 'An active key exists, but raw keys are only shown once.'}{' '}
          Create a new key if you need to copy the raw value again.
        </WarningPanel>
      )}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-background p-3 ring-1 ring-border">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold capitalize">{value}</p>
    </div>
  )
}

function WarningPanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-3xl bg-amber-50 p-5 text-sm leading-6 text-amber-900 ring-1 ring-amber-200">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
      <p>{children}</p>
    </div>
  )
}
