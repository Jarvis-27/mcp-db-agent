import { redirect } from 'next/navigation'

interface Props {
  searchParams: Promise<{ oauth?: string; oauth_error?: string }>
}

export default async function SetupClientsRedirectPage({ searchParams }: Props) {
  const { oauth, oauth_error } = await searchParams
  const params = new URLSearchParams()
  if (oauth) params.set('oauth', oauth)
  if (oauth_error) params.set('oauth_error', oauth_error)
  const qs = params.toString()
  redirect(`/app/setup/clients${qs ? `?${qs}` : ''}`)
}
