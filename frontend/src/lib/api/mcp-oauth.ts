'use server'

import { backendFetch } from '@/lib/api/backend'
import type { OAuthLinkStatusResponse } from '@/types/api'

export type StartMcpOauthLinkActionResult =
  | { ok: true; authorizationUrl: string }
  | { ok: false; error: string; redirectTo?: string }

export type UnlinkMcpOauthLinkActionResult =
  | { ok: true }
  | { ok: false; error: string; redirectTo?: string }

export async function getMcpOauthLinkStatusOrRedirect(): Promise<OAuthLinkStatusResponse> {
  const res = await backendFetch('/v1/account/mcp-oauth/status', { cache: 'no-store' })

  if (res.status === 401) {
    return Promise.reject(new Error('UNAUTHORIZED'))
  }

  if (!res.ok) {
    throw new Error('Failed to load MCP OAuth link status.')
  }

  return res.json()
}

export async function startMcpOauthLinkAction(): Promise<StartMcpOauthLinkActionResult> {
  const res = await backendFetch('/v1/account/mcp-oauth/start', {
    method: 'POST',
    cache: 'no-store',
  })

  if (res.status === 401) {
    return { ok: false, error: 'Session expired.', redirectTo: '/login' }
  }

  if (!res.ok) {
    try {
      const err = await res.json()
      return { ok: false, error: err.detail ?? 'Failed to start OAuth linking.' }
    } catch {
      return { ok: false, error: 'Failed to start OAuth linking.' }
    }
  }

  const payload: { authorization_url: string } = await res.json()
  return { ok: true, authorizationUrl: payload.authorization_url }
}

export async function unlinkMcpOauthLinkAction(): Promise<UnlinkMcpOauthLinkActionResult> {
  const res = await backendFetch('/v1/account/mcp-oauth/link', {
    method: 'DELETE',
    cache: 'no-store',
  })

  if (res.status === 401) {
    return { ok: false, error: 'Session expired.', redirectTo: '/login' }
  }

  if (!res.ok) {
    try {
      const err = await res.json()
      return { ok: false, error: err.detail ?? 'Failed to unlink OAuth identity.' }
    } catch {
      return { ok: false, error: 'Failed to unlink OAuth identity.' }
    }
  }

  return { ok: true }
}
