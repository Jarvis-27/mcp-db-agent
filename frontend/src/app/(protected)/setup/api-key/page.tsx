import { redirect } from 'next/navigation'

export default function ApiKeySetupRedirectPage() {
  redirect('/app/api-keys')
}
