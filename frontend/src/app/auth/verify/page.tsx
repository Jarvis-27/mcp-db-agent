import { redirect } from 'next/navigation'
import Link from 'next/link'
import { AlertCircle } from 'lucide-react'
import { BrandMark } from '@/components/brand-mark'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

interface Props {
  searchParams: Promise<{ token?: string; error?: string }>
}

export default async function VerifyEmailPage({ searchParams }: Props) {
  const { token, error } = await searchParams

  if (error) {
    return (
      <AuthErrorShell
        title="Verification failed"
        description="The link could not be used."
        message={error}
        actionHref="/signup"
        actionLabel="Create a new account"
      />
    )
  }

  if (!token) {
    return (
      <AuthErrorShell
        title="Invalid verification link"
        description="This verification link is missing a token."
        message="Please use the full link from your verification email."
        actionHref="/signup"
        actionLabel="Back to signup"
      />
    )
  }

  redirect(`/auth/verify/complete?token=${encodeURIComponent(token)}`)
}

function AuthErrorShell({
  title,
  description,
  message,
  actionHref,
  actionLabel,
}: {
  title: string
  description: string
  message: string
  actionHref: string
  actionLabel: string
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
              Verification links expire after 60 minutes and can only be used once.{' '}
              <Link href={actionHref} className="font-medium text-primary underline-offset-4 hover:underline">
                {actionLabel}
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
