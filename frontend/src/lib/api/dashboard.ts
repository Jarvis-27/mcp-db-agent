import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type {
  AccountStatusResponse,
  ApiKeyResponse,
  OAuthLinkStatusResponse,
  RecentQueriesResponse,
  SetupPayloadResponse,
} from '@/types/api'

export async function getDashboardDataOrRedirect() {
  const [statusRes, payloadRes, keysRes, oauthRes] = await Promise.all([
    backendFetch('/v1/account/status', { cache: 'no-store' }),
    backendFetch('/v1/account/setup-payloads', {
      method: 'POST',
      body: JSON.stringify({ raw_api_key: null }),
      cache: 'no-store',
    }),
    backendFetch('/v1/account/api-keys', { cache: 'no-store' }),
    backendFetch('/v1/account/mcp-oauth/status', { cache: 'no-store' }),
  ])

  if (statusRes.status === 401) redirect('/login')

  const status: AccountStatusResponse = statusRes.ok ? await statusRes.json() : null
  const payload: SetupPayloadResponse | null =
    payloadRes.ok ? await payloadRes.json() : null
  const keys: ApiKeyResponse[] = keysRes.ok ? await keysRes.json() : []
  const oauth: OAuthLinkStatusResponse | null =
    oauthRes.ok ? await oauthRes.json() : null

  return { status, payload, keys, oauth }
}

export async function getRecentQueriesOrNull(): Promise<RecentQueriesResponse | null> {
  try {
    const res = await backendFetch('/v1/account/usage/recent?limit=10', {
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}
