'use server'

import { backendFetch } from '@/lib/api/backend'
import type { CreatedApiKeyResponse } from '@/types/api'

export type CreateApiKeyActionResult =
  | { ok: true; key: CreatedApiKeyResponse }
  | { ok: false; error: string; redirectTo?: string }

export type RevokeApiKeyActionResult =
  | { ok: true; apiKeyId: string }
  | { ok: false; error: string; redirectTo?: string }

export async function createApiKeyAction(name: string): Promise<CreateApiKeyActionResult> {
  const normalizedName = name.trim() || 'default'

  const res = await backendFetch('/v1/account/api-keys', {
    method: 'POST',
    body: JSON.stringify({ name: normalizedName, scopes: ['mcp_read'] }),
  })

  if (res.status === 401) {
    return { ok: false, error: 'Session expired.', redirectTo: '/login' }
  }

  if (!res.ok) {
    try {
      const err = await res.json()
      return { ok: false, error: err.detail ?? 'Failed to create API key.' }
    } catch {
      return { ok: false, error: 'Failed to create API key.' }
    }
  }

  const key: CreatedApiKeyResponse = await res.json()
  return { ok: true, key }
}

export async function revokeApiKeyAction(apiKeyId: string): Promise<RevokeApiKeyActionResult> {
  const res = await backendFetch(`/v1/account/api-keys/${apiKeyId}`, {
    method: 'DELETE',
  })

  if (res.status === 401) {
    return { ok: false, error: 'Session expired.', redirectTo: '/login' }
  }

  if (!res.ok) {
    try {
      const err = await res.json()
      return { ok: false, error: err.detail ?? 'Failed to revoke API key.' }
    } catch {
      return { ok: false, error: 'Failed to revoke API key.' }
    }
  }

  return { ok: true, apiKeyId }
}