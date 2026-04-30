import { redirect } from 'next/navigation'
import { getApiKeysOrRedirect, getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { ApiKeyManager } from '@/components/api-key-manager'
import { PageHeader } from '@/components/page-header'
import { sanitizeReturnTo } from '@/lib/return-to'

interface Props {
  searchParams: Promise<{ returnTo?: string }>
}

export default async function AppApiKeysPage({ searchParams }: Props) {
  const status = await getOnboardingStatusOrRedirect()

  if (status.status !== 'setup_complete') {
    if (status.status === 'pending_db_connection') redirect('/app/setup/database')
    else redirect('/setup/status')
  }

  const keys = await getApiKeysOrRedirect()
  const { returnTo } = await searchParams
  const safeReturnTo = sanitizeReturnTo(returnTo)

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Authentication"
        title="API keys"
        description="Manage bearer credentials for MCP clients and integrations that do not use OAuth."
      />

      <div className="max-w-4xl">
        <ApiKeyManager initialKeys={keys} mode="manage" returnTo={safeReturnTo} />
      </div>
    </div>
  )
}
