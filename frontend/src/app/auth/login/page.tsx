'use client'

import { use, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { AlertCircle } from 'lucide-react'
import { BrandMark } from '@/components/brand-mark'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useDetectedTimezone } from '@/lib/use-detected-timezone'

interface Props {
  searchParams: Promise<{ token?: string; error?: string }>
}

export default function LoginCallbackPage({ searchParams }: Props) {
  const { token, error } = use(searchParams)
  const router = useRouter()
  const tz = useDetectedTimezone()

  useEffect(() => {
    if (error || !token) return
    const params = new URLSearchParams({ token })
    if (tz) params.set('tz', tz)
    router.replace(`/auth/login/complete?${params.toString()}`)
  }, [error, router, token, tz])

  if (error) {
    return (
      <AuthErrorShell
        title="Sign-in failed"
        description="The link could not be used."
        message={error}
      />
    )
  }

  if (!token) {
    return (
      <AuthErrorShell
        title="Invalid sign-in link"
        description="This sign-in link is missing a token."
        message="Please use the full link from your email."
      />
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <p className="text-sm text-muted-foreground">Signing you in…</p>
    </main>
  )
}

function AuthErrorShell({
  title,
  description,
  message,
}: {
  title: string
  description: string
  message: string
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <BrandMark className="justify-center" />
        </div>
        <Card className="rounded-3xl shadow-xl shadow-primary/10">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-red-50 text-red-700 ring-1 ring-red-200">
              <AlertCircle className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert variant="destructive">
              <AlertDescription>{message}</AlertDescription>
            </Alert>
            <p className="text-sm leading-6 text-muted-foreground">
              Sign-in links expire after 30 minutes and can only be used once.{' '}
              <Link href="/login" className="font-medium text-primary underline-offset-4 hover:underline">
                Request a new sign-in link
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
