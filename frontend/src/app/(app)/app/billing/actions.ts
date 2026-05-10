'use server'

import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type { BillingSessionResponse } from '@/types/api'

export async function createCheckoutSessionAction() {
  const res = await backendFetch('/v1/account/billing/checkout-session', {
    method: 'POST',
    body: JSON.stringify({}),
    cache: 'no-store',
  })

  if (res.status === 401) redirect('/login')
  if (!res.ok) redirect(`/app/billing?error=${encodeURIComponent(await errorText(res))}`)

  const payload: BillingSessionResponse = await res.json()
  redirect(payload.url)
}

export async function createPortalSessionAction() {
  const res = await backendFetch('/v1/account/billing/portal-session', {
    method: 'POST',
    body: JSON.stringify({}),
    cache: 'no-store',
  })

  if (res.status === 401) redirect('/login')
  if (!res.ok) redirect(`/app/billing?error=${encodeURIComponent(await errorText(res))}`)

  const payload: BillingSessionResponse = await res.json()
  redirect(payload.url)
}

async function errorText(res: Response): Promise<string> {
  try {
    const payload = await res.json()
    return payload.detail ?? 'Billing action failed.'
  } catch {
    return 'Billing action failed.'
  }
}
