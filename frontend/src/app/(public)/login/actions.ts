'use server'

import { backendFetchPublic } from '@/lib/api/backend'

type State = { success?: boolean; error?: string } | null

export async function requestLoginLinkAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const email = formData.get('email')?.toString().trim()
  if (!email) return { error: 'Email address is required.' }

  const res = await backendFetchPublic('/v1/auth/request-login-link', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })

  // Backend always returns 202 to avoid user enumeration; we mirror that.
  if (res.status === 202 || res.ok) return { success: true }

  // Rate-limit or other server error
  if (res.status === 429) return { error: 'Too many requests. Please wait a minute and try again.' }

  return { success: true } // still show success to avoid enumeration
}
