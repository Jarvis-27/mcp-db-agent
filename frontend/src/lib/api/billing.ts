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
