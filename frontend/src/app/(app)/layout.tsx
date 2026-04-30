import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { AppShell } from '@/components/app-shell'

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const cookieStore = await cookies()
  const session = cookieStore.get('mdb_session')?.value

  if (!session) {
    redirect('/login')
  }

  return <AppShell>{children}</AppShell>
}
