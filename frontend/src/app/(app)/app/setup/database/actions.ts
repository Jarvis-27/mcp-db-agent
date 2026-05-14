'use server'

import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type { SetupPayloadResponse } from '@/types/api'

type State = { error?: string; errorCode?: string } | null

export async function getStaticOutboundIpAction(): Promise<string | null> {
  const res = await backendFetch('/v1/account/status', { cache: 'no-store' })
  if (!res.ok) return null
  try {
    const data = await res.json()
    return typeof data?.static_outbound_ip === 'string' ? data.static_outbound_ip : null
  } catch {
    return null
  }
}

function _extractErrorDetail(payload: unknown): { message: string; code?: string } {
  if (
    payload &&
    typeof payload === 'object' &&
    'detail' in payload
  ) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return { message: detail }
    if (detail && typeof detail === 'object') {
      const d = detail as { message?: unknown; code?: unknown }
      return {
        message: typeof d.message === 'string' ? d.message : 'Unknown error.',
        code: typeof d.code === 'string' ? d.code : undefined,
      }
    }
  }
  return { message: 'Unknown error.' }
}

export async function submitDatabaseAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const method = formData.get('connection_method')?.toString() ?? 'guided'
  let body: Record<string, string | number | null> = { name: 'primary' }

  if (method === 'url') {
    const databaseUrl = formData.get('database_url')?.toString().trim()
    if (!databaseUrl) return { error: 'Database URL is required.' }
    body = {
      ...body,
      connection_method: 'url',
      database_url: databaseUrl,
    }
  } else {
    const provider = formData.get('provider')?.toString() || 'generic_postgres'
    const host = formData.get('host')?.toString().trim()
    const portText = formData.get('port')?.toString().trim()
    const database = formData.get('database')?.toString().trim()
    const username = formData.get('username')?.toString().trim()
    const password = formData.get('password')?.toString() ?? ''
    const sslmode = formData.get('sslmode')?.toString() || 'require'

    if (!host || !database || !username || !password) {
      return { error: 'Host, database name, username, and password are required.' }
    }

    const port = Number(portText || '5432')
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      return { error: 'Port must be a number between 1 and 65535.' }
    }

    body = {
      ...body,
      connection_method: 'guided',
      provider,
      host,
      port,
      database,
      username,
      password,
      sslmode,
    }
  }

  const res = await backendFetch('/v1/account/database', {
    method: 'PUT',
    body: JSON.stringify(body),
  })

  if (res.ok) {
    const payloadRes = await backendFetch('/v1/account/setup-payloads', {
      method: 'POST',
      body: JSON.stringify({ raw_api_key: null }),
      cache: 'no-store',
    })

    if (payloadRes.ok) {
      const payload: SetupPayloadResponse = await payloadRes.json()
      if (
        payload.mcp_auth_mode === 'api_key_only' &&
        payload.api_key_state.active_key_count === 0
      ) {
        redirect('/app/api-keys?returnTo=%2Fapp%2Fsetup%2Fclients')
      }
    }

    redirect('/app/setup/clients')
  }

  if (res.status === 401) redirect('/login')

  if (res.status === 409) {
    try {
      const err = await res.json()
      const detail = _extractErrorDetail(err)
      return { error: detail.message || 'Database already connected.', errorCode: detail.code }
    } catch {
      return { error: 'Database already connected.' }
    }
  }

  try {
    const err = await res.json()
    const detail = _extractErrorDetail(err)
    return {
      error:
        detail.message ||
        'Could not connect to the database. Check the URL and try again.',
      errorCode: detail.code,
    }
  } catch {
    return { error: 'Could not connect to the database. Check the URL and try again.' }
  }
}
