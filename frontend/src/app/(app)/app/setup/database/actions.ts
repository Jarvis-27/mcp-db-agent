'use server'

import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type { SetupPayloadResponse } from '@/types/api'

type State = { error?: string } | null

export async function submitDatabaseAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const databaseUrl = formData.get('database_url')?.toString().trim()

  if (!databaseUrl) return { error: 'Database URL is required.' }

  const res = await backendFetch('/v1/account/database', {
    method: 'PUT',
    body: JSON.stringify({ database_url: databaseUrl, name: 'primary' }),
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
      return { error: err.detail ?? 'Database already connected.' }
    } catch {
      return { error: 'Database already connected.' }
    }
  }

  try {
    const err = await res.json()
    return {
      error:
        err.detail ??
        'Could not connect to the database. Check the URL and try again.',
    }
  } catch {
    return { error: 'Could not connect to the database. Check the URL and try again.' }
  }
}
