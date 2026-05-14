import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type {
  AdminMeResponse,
  AdminOverviewResponse,
  AdminQueryListResponse,
  AdminUserDetailResponse,
  AdminUsersListResponse,
} from '@/types/api'

/** Loads /v1/admin/me. Redirects on 401, returns null on 403/other. */
export async function getAdminMe(): Promise<AdminMeResponse | null> {
  const res = await backendFetch('/v1/admin/me', { cache: 'no-store' })
  if (res.status === 401) redirect('/login')
  if (!res.ok) return null
  return res.json()
}

export async function getAdminOverview(): Promise<AdminOverviewResponse | null> {
  const res = await backendFetch('/v1/admin/overview', { cache: 'no-store' })
  if (res.status === 401) redirect('/login')
  if (!res.ok) return null
  return res.json()
}

export interface AdminListUsersParams {
  q?: string
  status?: string
  plan?: string
  limit?: number
  offset?: number
}

export async function getAdminUsers(
  params: AdminListUsersParams = {},
): Promise<AdminUsersListResponse | null> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  if (params.plan) qs.set('plan', params.plan)
  qs.set('limit', String(params.limit ?? 25))
  qs.set('offset', String(params.offset ?? 0))

  const res = await backendFetch(`/v1/admin/users?${qs.toString()}`, {
    cache: 'no-store',
  })
  if (res.status === 401) redirect('/login')
  if (!res.ok) return null
  return res.json()
}

export async function getAdminUserDetail(
  userId: string,
): Promise<AdminUserDetailResponse | null> {
  const res = await backendFetch(
    `/v1/admin/users/${encodeURIComponent(userId)}`,
    { cache: 'no-store' },
  )
  if (res.status === 401) redirect('/login')
  if (res.status === 404) return null
  if (!res.ok) return null
  return res.json()
}

export interface AdminListQueriesParams {
  user_id?: string
  success?: 'true' | 'false'
  error_code?: string
  since?: string
  limit?: number
  offset?: number
}

export async function getAdminQueries(
  params: AdminListQueriesParams = {},
): Promise<AdminQueryListResponse | null> {
  const qs = new URLSearchParams()
  if (params.user_id) qs.set('user_id', params.user_id)
  if (params.success !== undefined) qs.set('success', params.success)
  if (params.error_code) qs.set('error_code', params.error_code)
  if (params.since) qs.set('since', params.since)
  qs.set('limit', String(params.limit ?? 25))
  qs.set('offset', String(params.offset ?? 0))

  const res = await backendFetch(`/v1/admin/queries?${qs.toString()}`, {
    cache: 'no-store',
  })
  if (res.status === 401) redirect('/login')
  if (!res.ok) return null
  return res.json()
}
