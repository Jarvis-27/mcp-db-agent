import { redirect } from 'next/navigation'
import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/page-header'
import { getOnboardingStatusOrRedirect } from '@/lib/api/owner'
import { getStatusPageCopy, resolveStatusResponseDestination } from '@/lib/onboarding'

export default async function SetupStatusPage() {
  const status = await getOnboardingStatusOrRedirect()
  const destination = resolveStatusResponseDestination(status)

  if (destination !== '/setup/status') {
    redirect(destination)
  }

  const copy = getStatusPageCopy(status.status, status.account_status, status.blockers)

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Account status"
        title={copy.title}
        description={copy.detail}
      />

      <Card className="rounded-3xl shadow-sm">
        <CardHeader>
          <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-50 text-amber-800 ring-1 ring-amber-200">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <CardTitle className="text-2xl">Current account state</CardTitle>
          <CardDescription>Review the status below before attempting another setup step.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Alert>
            <AlertTitle>Next step</AlertTitle>
            <AlertDescription>{status.next_step}</AlertDescription>
          </Alert>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border bg-background p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Onboarding status
              </p>
              <p className="mt-2 font-medium">{status.status.replaceAll('_', ' ')}</p>
            </div>
            <div className="rounded-2xl border bg-background p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Account status
              </p>
              <p className="mt-2 font-medium">{status.account_status}</p>
            </div>
          </div>

          {status.blockers.length > 0 && (
            <div className="space-y-3">
              <p className="font-medium">Active blockers</p>
              <div className="flex flex-wrap gap-2">
                {status.blockers.map((blocker) => (
                  <span
                    key={blocker}
                    className="rounded-full border bg-background px-3 py-1.5 text-sm text-muted-foreground"
                  >
                    {blocker.replaceAll('_', ' ')}
                  </span>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
