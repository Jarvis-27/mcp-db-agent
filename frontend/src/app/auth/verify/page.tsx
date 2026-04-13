import { redirect } from 'next/navigation'
import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

interface Props {
  searchParams: Promise<{ token?: string; error?: string }>
}

export default async function VerifyEmailPage({ searchParams }: Props) {
  const { token, error } = await searchParams

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Verification failed</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
            <p className="text-sm text-muted-foreground">
              The link may have expired (valid for 60 minutes) or already been used.{' '}
              <Link href="/signup" className="underline underline-offset-4">Sign up</Link>{' '}
              to get a new one.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Invalid link</CardTitle>
            <CardDescription>This verification link is missing a token.</CardDescription>
          </CardHeader>
          <CardContent>
            <Alert variant="destructive">
              <AlertDescription>
                Please use the full link from your verification email, or{' '}
                <Link href="/signup" className="underline">sign up again</Link>.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      </div>
    )
  }

  redirect(`/auth/verify/complete?token=${encodeURIComponent(token)}`)
}
