import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type { BillingSummaryResponse } from '@/types/api'

export async function getBillingSummaryOrRedirect(): Promise<BillingSummaryResponse> {
  const res = await backendFetch('/v1/account/billing', { cache: 'no-store' })
  if (res.status === 401) redirect('/login')
  if (!res.ok) {
    throw new Error('Could not load billing summary.')
  }
  return res.json()
}

export async function confirmCheckoutSession(sessionId: string): Promise<void> {
  const res = await backendFetch('/v1/account/billing/confirm-session', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
    cache: 'no-store',
  })
  if (!res.ok) {
    console.error(
      'confirmCheckoutSession failed',
      res.status,
      await res.text().catch(() => ''),
    )
  }
}
