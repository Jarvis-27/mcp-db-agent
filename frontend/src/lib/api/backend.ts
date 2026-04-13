/**
 * Server-side backend API helper.
 * Reads the mdb_session HTTP-only cookie and injects it as an owner-session header.
 * Only call this from Server Components, Server Actions, or Route Handlers.
 */

import { cookies } from 'next/headers'

const BACKEND_URL = process.env.BACKEND_API_URL ?? 'http://localhost:8000'

export async function backendFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const cookieStore = await cookies()
  const session = cookieStore.get('mdb_session')?.value ?? ''

  return fetch(`${BACKEND_URL}/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(session ? { 'x-owner-session': session } : {}),
      ...(init?.headers ?? {}),
    },
  })
}

/** Unauthenticated backend call (registration, login link request). */
export async function backendFetchPublic(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(`${BACKEND_URL}/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
}
