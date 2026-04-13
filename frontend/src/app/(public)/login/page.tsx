'use client'

import { useActionState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { requestLoginLinkAction } from './actions'

type State = { success?: boolean; error?: string } | null

export default function LoginPage() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    requestLoginLinkAction,
    null,
  )

  if (state?.success) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Check your email</CardTitle>
          <CardDescription>
            If an account exists for that address, we sent a sign-in link. Click
            it to continue.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            The link expires in 30&nbsp;minutes. If you don&apos;t see it, check your
            spam folder.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>
          We&apos;ll email you a sign-in link — no password required.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          {state?.error && (
            <Alert variant="destructive">
              <AlertDescription>{state.error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="email">Email address</Label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="you@example.com"
              required
              autoComplete="email"
            />
          </div>

          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? 'Sending link…' : 'Send sign-in link'}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground mt-4">
          Don&apos;t have an account?{' '}
          <Link href="/signup" className="underline underline-offset-4 hover:text-primary">
            Sign up
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
