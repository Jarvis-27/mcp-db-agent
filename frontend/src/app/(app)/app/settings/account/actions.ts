'use server'

import { revalidatePath } from 'next/cache'
import { backendFetch } from '@/lib/api/backend'

type State = { success?: boolean; error?: string; timezone?: string } | null

export async function updateTimezoneAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const timezone = formData.get('timezone')?.toString().trim()
  if (!timezone) {
    return { error: 'Time zone is required.' }
  }

  const res = await backendFetch('/v1/account/preferences', {
    method: 'PUT',
    body: JSON.stringify({ timezone }),
    cache: 'no-store',
  })

  if (!res.ok) {
    try {
      const data = await res.json()
      return { error: data.detail ?? 'Failed to update time zone.' }
    } catch {
      return { error: 'Failed to update time zone.' }
    }
  }

  const data = await res.json()
  revalidatePath('/app/settings/account')
  revalidatePath('/app/usage')
  revalidatePath('/app/dashboard')
  return { success: true, timezone: data.timezone as string }
}
