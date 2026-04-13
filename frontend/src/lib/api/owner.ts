import { redirect } from 'next/navigation'
import { backendFetch } from '@/lib/api/backend'
import type { ApiKeyResponse, OnboardingStatusResponse } from '@/types/api'

export async function getOnboardingStatusOrRedirect(): Promise<OnboardingStatusResponse> {
  const res = await backendFetch('/v1/onboarding/status', { cache: 'no-store' })

  if (res.status === 401) {
    redirect('/login')
  }

  if (!res.ok) {
    throw new Error('Failed to load onboarding status.')
  }

  return res.json()
}

export async function getApiKeysOrRedirect(): Promise<ApiKeyResponse[]> {
  const res = await backendFetch('/v1/api-keys', { cache: 'no-store' })

  if (res.status === 401) {
    redirect('/login')
  }

  if (!res.ok) {
    throw new Error('Failed to load API keys.')
  }

  return res.json()
}
