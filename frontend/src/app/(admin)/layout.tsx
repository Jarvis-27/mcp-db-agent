import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { AdminShell } from '@/components/admin-shell'
import { getAdminMe } from '@/lib/api/admin'

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const cookieStore = await cookies()
  const session = cookieStore.get('mdb_session')?.value
  if (!session) redirect('/login')

  const me = await getAdminMe()
  if (!me || !me.is_admin) redirect('/app/dashboard')

  return <AdminShell adminEmail={me.email}>{children}</AdminShell>
}
