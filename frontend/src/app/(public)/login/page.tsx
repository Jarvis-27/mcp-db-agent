'use client'

import { useActionState } from 'react'
import Link from 'next/link'
import { ArrowRight, Mail, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useDetectedTimezone } from '@/lib/use-detected-timezone'
import { requestLoginLinkAction } from './actions'

type State = { success?: boolean; error?: string } | null

export default function LoginPage() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    requestLoginLinkAction,
    null,
  )
  const timezone = useDetectedTimezone()

  return (
    <main className="mx-auto grid min-h-[calc(100vh-8rem)] max-w-5xl items-center gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[0.85fr_1fr] lg:px-8">
      <section className="max-w-lg">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          Welcome back
        </p>
        <h1 className="mt-4 text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
          Return to your database control room.
        </h1>
        <p className="mt-5 text-base leading-7 text-muted-foreground">
          We use secure email links for the web app. Your raw session token stays
          in an HTTP-only cookie and is never exposed to client-side JavaScript.
        </p>
      </section>

      {state?.success ? (
        <Card className="rounded-3xl shadow-xl shadow-primary/10">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
              <Mail className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">Check your email</CardTitle>
            <CardDescription className="text-base leading-7">
              If an account exists for that address, we sent a sign-in link.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-muted-foreground">
              The link expires in 30 minutes. If you do not see it, check your
              spam folder.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card className="rounded-3xl shadow-xl shadow-primary/10">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">Sign in</CardTitle>
            <CardDescription className="text-base leading-7">
              Enter your email and we will send a password-free sign-in link.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action={formAction} className="space-y-4">
              {state?.error && (
                <Alert variant="destructive">
                  <AlertDescription>{state.error}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="email">Email address</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                  className="h-11"
                />
              </div>

              <input type="hidden" name="timezone" value={timezone} />

              <Button type="submit" className="h-11 w-full" disabled={isPending}>
                {isPending ? 'Sending link...' : 'Send sign-in link'}
                {!isPending && <ArrowRight className="h-4 w-4" />}
              </Button>
            </form>

            <p className="mt-5 text-center text-sm text-muted-foreground">
              New to PlainQuery?{' '}
              <Link href="/signup" className="font-medium text-primary underline-offset-4 hover:underline">
                Create an account
              </Link>
            </p>
          </CardContent>
        </Card>
      )}
    </main>
  )
}
