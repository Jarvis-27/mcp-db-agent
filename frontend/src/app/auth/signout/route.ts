import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

export async function POST() {
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
