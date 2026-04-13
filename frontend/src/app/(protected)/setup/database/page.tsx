'use client'

import { useActionState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { submitDatabaseAction } from './actions'

type State = { error?: string } | null

const DB_EXAMPLES = [
  {
    label: 'PostgreSQL',
    value: 'postgresql://user:password@host:5432/dbname',
  },
  { label: 'MySQL', value: 'mysql+pymysql://user:password@host:3306/dbname' },
]

export default function DatabaseSetupPage() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    submitDatabaseAction,
    null,
  )

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Connect your database</h2>
        <p className="text-muted-foreground text-sm mt-1">
          We&apos;ll validate the connection and activate your free plan automatically.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Database URL</CardTitle>
          <CardDescription>
            Your credentials are encrypted at rest and never used except to
            execute your queries.
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
              <Label htmlFor="database_url">Connection string</Label>
              <Input
                id="database_url"
                name="database_url"
                type="text"
                placeholder="postgresql://user:password@host:5432/dbname"
                required
                className="font-mono text-sm"
              />
            </div>

            <div className="space-y-2">
              <p className="text-xs text-muted-foreground font-medium">
                Supported formats
              </p>
              <div className="flex flex-wrap gap-2">
                {DB_EXAMPLES.map((ex) => (
                  <Badge key={ex.label} variant="secondary" className="font-mono text-xs">
                    {ex.label}
                  </Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                SQLite is not supported in hosted mode. Ensure your database
                is reachable from the internet.
              </p>
            </div>

            <Button type="submit" className="w-full" disabled={isPending}>
              {isPending ? 'Testing connection…' : 'Connect database'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="border-dashed">
        <CardContent className="pt-6">
          <p className="text-sm font-medium mb-2">Security note</p>
          <p className="text-xs text-muted-foreground">
            Connection strings are validated against a safety policy (no private
            IPs, no path traversal) and encrypted with Fernet symmetric
            encryption before storage.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
