export type ReturnToRoute = '/api-keys' | '/setup/clients'

const ALLOWED_RETURN_TO: ReadonlySet<ReturnToRoute> = new Set([
  '/api-keys',
  '/setup/clients',
])

export function sanitizeReturnTo(value: string | undefined): ReturnToRoute | null {
  if (!value) {
    return null
  }

  return ALLOWED_RETURN_TO.has(value as ReturnToRoute) ? (value as ReturnToRoute) : null
}
