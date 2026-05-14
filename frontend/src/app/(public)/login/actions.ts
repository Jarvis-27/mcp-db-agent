'use server'

import { redirect } from 'next/navigation'
import { backendFetchPublic } from '@/lib/api/backend'

type State = { success?: boolean; error?: string } | null

export async function requestLoginLinkAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const email = formData.get('email')?.toString().trim()
  const timezone = formData.get('timezone')?.toString().trim() || null
  if (!email) return { error: 'Email address is required.' }

  const res = await backendFetchPublic('/v1/auth/request-login-link', {
    method: 'POST',
    body: JSON.stringify({ email, timezone }),
  })

  if (res.status === 404) {
    redirect(`/signup?email=${encodeURIComponent(email)}&reason=no-account`)
  }
  if (res.status === 429) {
    return { error: 'Too many requests. Please wait a minute and try again.' }
  }
  if (!res.ok) {
    return { error: 'Could not send sign-in link. Please try again.' }
  }
  return { success: true }
}
