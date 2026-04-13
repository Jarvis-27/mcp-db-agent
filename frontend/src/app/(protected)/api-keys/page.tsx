import { redirect } from 'next/navigation'
import { ApiKeyManager } from '@/components/api-key-manager'
import { getApiKeysOrRedirect, getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { resolveStatusResponseDestination } from '@/lib/onboarding'
import { sanitizeReturnTo } from '@/lib/return-to'

interface Props {
  searchParams: Promise<{ returnTo?: string }>
}

export default async function ApiKeysPage({ searchParams }: Props) {
  const status = await getOnboardingStatusOrRedirect()
  const destination = resolveStatusResponseDestination(status)

  if (destination !== '/setup/clients') {
    redirect(destination)
  }

  const keys = await getApiKeysOrRedirect()
  const { returnTo } = await searchParams
  const safeReturnTo = sanitizeReturnTo(returnTo)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">API keys</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Manage the credentials your MCP clients use to authenticate.
        </p>
      </div>

      <ApiKeyManager initialKeys={keys} mode="manage" returnTo={safeReturnTo} />
    </div>
  )
}
