import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

export function getBackendApiUrl(): string {
  return process.env.BACKEND_API_URL ?? 'http://localhost:8000'
}

export async function getApiErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const err = await res.json()
    if (typeof err.detail === 'string' && err.detail.trim().length > 0) {
      return err.detail
    }
  } catch {
    // Ignore invalid JSON and fall back to the default message.
  }

  return fallback
}

export function redirectWithError(
  request: NextRequest,
  pathname: '/auth/login' | '/auth/verify',
  message: string,
): NextResponse {
  const url = new URL(pathname, request.url)
  url.searchParams.set('error', message)
  return NextResponse.redirect(url)
}

export function setOwnerSessionCookie(
  response: NextResponse,
  ownerSessionToken: string,
  expiresInSeconds: number,
): void {
  response.cookies.set('mdb_session', ownerSessionToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: expiresInSeconds,
    path: '/',
  })
}
