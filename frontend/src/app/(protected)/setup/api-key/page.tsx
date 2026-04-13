import { redirect } from 'next/navigation'
import { ApiKeyManager } from '@/components/api-key-manager'
import { getApiKeysOrRedirect, getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { resolveStatusResponseDestination } from '@/lib/onboarding'

export default async function ApiKeySetupPage() {
  const status = await getOnboardingStatusOrRedirect()
  const destination = resolveStatusResponseDestination(status)

  if (destination !== '/setup/clients') {
    redirect(destination)
  }

  const keys = await getApiKeysOrRedirect()
  const hasActiveKey = keys.some((key) => key.revoked_at === null)

  if (hasActiveKey) {
    redirect('/setup/clients')
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Create your first API key</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Your MCP clients use this key to authenticate. Create it here, save it once,
          and continue to the client configuration step.
        </p>
      </div>

      <ApiKeyManager initialKeys={keys} mode="onboarding" />
    </div>
  )
}
