'use server'

import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'

type State = { error?: string } | null

export async function submitDatabaseAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const databaseUrl = formData.get('database_url')?.toString().trim()

  if (!databaseUrl) return { error: 'Database URL is required.' }

  const res = await backendFetch('/v1/onboarding/database', {
    method: 'POST',
    body: JSON.stringify({ database_url: databaseUrl, name: 'primary' }),
  })

  if (res.ok) {
    redirect('/setup/api-key')
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
