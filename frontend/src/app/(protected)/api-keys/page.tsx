import { redirect } from 'next/navigation'

interface Props {
  searchParams: Promise<{ returnTo?: string }>
}

export default async function ApiKeysRedirectPage({ searchParams }: Props) {
  const { returnTo } = await searchParams
  const params = new URLSearchParams()
  if (returnTo) params.set('returnTo', returnTo)
  const qs = params.toString()
  redirect(`/app/api-keys${qs ? `?${qs}` : ''}`)
}
