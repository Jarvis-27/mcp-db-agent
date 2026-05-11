import Link from 'next/link'
import { redirect } from 'next/navigation'
import {
  AlertTriangle,
  ArrowUpRight,
  CopyCheck,
  MessageSquareText,
  PlugZap,
} from 'lucide-react'
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
      <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
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
        eyebrow="§ setup · clients"
        title="Connect the place where people will ask questions."
        description="Copy the MCP endpoint and client-specific setup. Once connected, try a simple schema question first."
        action={
          <Link
            href="/app/usage"
            className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-10')}
          >
            View usage
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        }
      />

      <section className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
        <SectionCard
          eyebrow="endpoint"
          icon={PlugZap}
          title="MCP endpoint"
          description="Use this URL in every supported client."
        >
          <div className="mt-5">
            <CodeBlockWithCopy code={payload.mcp_url} inline />
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="auth"
          title="Auth mode"
          description="The generated instructions adapt to this deployment."
          headerAction={
            <StatusBadge
              variant={
                payload.oauth_enabled_for_mcp
                  ? 'connected'
                  : hasActiveKey
                    ? 'info'
                    : 'warning'
              }
              label={
                payload.oauth_enabled_for_mcp
                  ? 'OAuth ready'
                  : hasActiveKey
                    ? 'Key ready'
                    : 'Needs key'
              }
            />
          }
        >
          <div className="mt-5 grid gap-2 sm:grid-cols-3">
            <MiniStat label="Plan" value={payload.plan_code} />
            <MiniStat
              label="Daily quota"
              value={`${payload.quota_summary.daily_remaining}/${payload.quota_summary.daily_limit} left`}
            />
            <MiniStat
              label="API keys"
              value={`${payload.api_key_state.active_key_count} active`}
            />
          </div>
        </SectionCard>
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

      <SectionCard
        eyebrow="clients"
        icon={CopyCheck}
        title="Client instructions"
        description="Choose the client your team will actually use first."
      >
        <div className="mt-6">
          <ClientConfigPanel clients={payload.clients} />
        </div>
      </SectionCard>

      {payload.sample_prompts.length > 0 && (
        <SectionCard
          eyebrow="prompts"
          icon={MessageSquareText}
          title="First questions to try"
          description="Start with safe, simple checks before asking business questions."
        >
          <div className="mt-5 flex flex-wrap gap-2">
            {payload.sample_prompts.map((prompt) => (
              <span
                key={prompt}
                className="rounded-full border border-border bg-muted/40 px-3 py-1.5 font-mono text-[12px] text-foreground"
              >
                &quot;{prompt}&quot;
              </span>
            ))}
          </div>
        </SectionCard>
      )}

      {!hasActiveKey && payload.mcp_auth_mode === 'api_key_only' && (
        <WarningPanel>
          API-key auth is required for this deployment.{' '}
          <Link
            href="/app/api-keys"
            className="font-semibold underline underline-offset-4"
          >
            Create an API key
          </Link>{' '}
          and return to client setup.
        </WarningPanel>
      )}

      {hasActiveKey &&
        payload.api_key_state.requires_manual_key_entry &&
        payload.mcp_auth_mode === 'api_key_only' && (
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

function SectionCard({
  eyebrow,
  icon: Icon,
  title,
  description,
  headerAction,
  children,
}: {
  eyebrow: string
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  headerAction?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-4">
          {Icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon className="h-4 w-4" />
            </span>
          )}
          <div className="min-w-0">
            <p className="eyebrow text-primary">{eyebrow}</p>
            <h2 className="mt-1 font-display text-lg font-semibold -tracking-[0.02em]">
              {title}
            </h2>
            {description && (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            )}
          </div>
        </div>
        {headerAction && <div className="shrink-0">{headerAction}</div>}
      </div>
      {children}
    </section>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-mono text-[13px] font-semibold capitalize tabular-nums">
        {value}
      </p>
    </div>
  )
}

function WarningPanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-200/80 bg-amber-50/70 p-5 text-sm leading-6 text-amber-900">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <p>{children}</p>
    </div>
  )
}

