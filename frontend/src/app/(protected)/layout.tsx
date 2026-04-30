import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { BrandMark } from '@/components/brand-mark'

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
    <div className="min-h-screen bg-background">
      <header className="border-b bg-background/90 px-4 py-4 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <BrandMark />
          <form action={logoutAction}>
            <button
              type="submit"
              className="rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              Sign out
            </button>
          </form>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">{children}</main>
    </div>
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
    }).catch(() => {})
  }
  cookieStore.delete('mdb_session')
  redirect('/login')
}
