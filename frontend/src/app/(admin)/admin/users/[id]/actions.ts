'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'

async function _post(path: string, body?: object): Promise<{ ok: boolean; detail?: string }> {
  const res = await backendFetch(path, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
    cache: 'no-store',
  })
  if (res.status === 401) redirect('/login')
  if (res.ok) return { ok: true }
  let detail = 'Action failed.'
  try {
    const payload = await res.json()
    if (payload?.detail) detail = String(payload.detail)
  } catch {
    /* swallow */
  }
  return { ok: false, detail }
}

function _revalidate(userId: string) {
  revalidatePath(`/admin/users/${userId}`)
  revalidatePath('/admin/users')
  revalidatePath('/admin')
}

export async function suspendUserAction(userId: string, formData: FormData): Promise<void> {
  const reason = formData.get('reason')
  const body = typeof reason === 'string' && reason.trim() ? { reason: reason.trim() } : {}
  const result = await _post(`/v1/admin/users/${encodeURIComponent(userId)}/suspend`, body)
  if (!result.ok) {
    redirect(`/admin/users/${userId}?error=${encodeURIComponent(result.detail ?? '')}`)
  }
  _revalidate(userId)
}

export async function unsuspendUserAction(userId: string): Promise<void> {
  const result = await _post(`/v1/admin/users/${encodeURIComponent(userId)}/unsuspend`)
  if (!result.ok) {
    redirect(`/admin/users/${userId}?error=${encodeURIComponent(result.detail ?? '')}`)
  }
  _revalidate(userId)
}

export async function closeUserAction(userId: string): Promise<void> {
  const result = await _post(`/v1/admin/users/${encodeURIComponent(userId)}/close`)
  if (!result.ok) {
    redirect(`/admin/users/${userId}?error=${encodeURIComponent(result.detail ?? '')}`)
  }
  _revalidate(userId)
}

export async function revokeApiKeyAction(
  userId: string,
  apiKeyId: string,
): Promise<void> {
  const result = await _post(
    `/v1/admin/users/${encodeURIComponent(userId)}/api-keys/${encodeURIComponent(apiKeyId)}/revoke`,
  )
  if (!result.ok) {
    redirect(`/admin/users/${userId}?error=${encodeURIComponent(result.detail ?? '')}`)
  }
  _revalidate(userId)
}
