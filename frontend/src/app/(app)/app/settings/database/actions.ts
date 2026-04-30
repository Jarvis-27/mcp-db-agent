'use server'

import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'

type State = { error?: string; success?: boolean } | null

export async function updateDatabaseAction(
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
    return { success: true }
  }

  if (res.status === 401) redirect('/login')

  try {
    const err = await res.json()
    return { error: err.detail ?? 'Could not connect to the database. Check the URL and try again.' }
  } catch {
    return { error: 'Could not connect to the database. Check the URL and try again.' }
  }
}

export async function validateDatabaseAction(): Promise<State> {
  const res = await backendFetch('/v1/account/database/validate', {
    method: 'POST',
    cache: 'no-store',
  })

  if (res.status === 401) redirect('/login')

  if (res.ok) {
    return { success: true }
  }

  try {
    const err = await res.json()
    return { error: err.detail ?? 'Validation failed.' }
  } catch {
    return { error: 'Validation failed.' }
  }
}
