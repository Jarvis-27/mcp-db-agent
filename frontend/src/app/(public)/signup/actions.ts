'use server'

import { backendFetchPublic } from '@/lib/api/backend'

type State = { success?: boolean; error?: string } | null

export async function registerAction(
  _prevState: State,
  formData: FormData,
): Promise<State> {
  const email = formData.get('email')?.toString().trim()
  const tenantName = formData.get('tenant_name')?.toString().trim() || null

  if (!email) return { error: 'Email address is required.' }

  const res = await backendFetchPublic('/v1/users/register', {
    method: 'POST',
    body: JSON.stringify({ email, tenant_name: tenantName }),
  })

  if (res.status === 201) return { success: true }

  if (res.status === 403) return { error: 'Registration is currently closed.' }

  if (res.status === 409)
    return { error: 'An account with this email already exists. Try signing in.' }

  try {
    const data = await res.json()
    return { error: data.detail ?? 'Registration failed. Please try again.' }
  } catch {
    return { error: 'Registration failed. Please try again.' }
  }
}
