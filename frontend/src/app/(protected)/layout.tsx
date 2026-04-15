import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const cookieStore = await cookies()
  const session = cookieStore.get('mdb_session')?.value

  if (!session) {
    redirect('/login')
  }

  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background px-6 py-4 flex items-center justify-between">
        <span className="font-semibold text-sm">MCP Database Agent</span>
        <LogoutButton />
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">{children}</main>
    </div>
  )
}

function LogoutButton() {
  return (
    <form action={logoutAction}>
      <button
        type="submit"
        className="text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        Sign out
      </button>
    </form>
  )
}

async function logoutAction() {
  'use server'
  const cookieStore = await cookies()
  const session = cookieStore.get('mdb_session')?.value
  if (session) {
    const backendUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000'
    await fetch(`${backendUrl}/api/v1/auth/logout`, {
      method: 'POST',
      headers: { 'x-session-token': session },
    }).catch(() => {/* ignore network errors on logout */})
  }
  cookieStore.delete('mdb_session')
  redirect('/login')
}