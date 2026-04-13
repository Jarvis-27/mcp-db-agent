import { redirect } from 'next/navigation'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{copy.title}</h2>
        <p className="text-muted-foreground text-sm mt-1">{copy.detail}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Current account state</CardTitle>
          <CardDescription>
            Review the status below before attempting another setup step.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Alert>
            <AlertTitle>Next step</AlertTitle>
            <AlertDescription>{status.next_step}</AlertDescription>
          </Alert>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Onboarding status</p>
              <p className="text-sm font-medium">{status.status.replaceAll('_', ' ')}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Account status</p>
              <p className="text-sm font-medium">{status.account_status}</p>
            </div>
          </div>

          {status.blockers.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium">Active blockers</p>
              <div className="flex flex-wrap gap-2">
                {status.blockers.map((blocker) => (
                  <span
                    key={blocker}
                    className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground"
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
