import { redirect } from 'next/navigation'
import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

interface Props {
  searchParams: Promise<{ token?: string; error?: string }>
}

export default async function LoginCallbackPage({ searchParams }: Props) {
  const { token, error } = await searchParams

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Sign-in failed</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
            <p className="text-sm text-muted-foreground">
              The link may have expired (valid for 30 minutes) or already been used.{' '}
              <Link href="/login" className="underline underline-offset-4">
                Request a new sign-in link
              </Link>
              .
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
            <CardDescription>This sign-in link is missing a token.</CardDescription>
          </CardHeader>
          <CardContent>
            <Alert variant="destructive">
              <AlertDescription>
                Please use the full link from your sign-in email, or{' '}
                <Link href="/login" className="underline">request a new one</Link>.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      </div>
    )
  }

  redirect(`/auth/login/complete?token=${encodeURIComponent(token)}`)
}
