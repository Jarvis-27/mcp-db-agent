'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CopyButton } from '@/components/copy-button'
import type { ClientSetupPayloadResponse } from '@/types/api'

interface Props {
  clients: {
    vs_code: ClientSetupPayloadResponse
    cursor: ClientSetupPayloadResponse
    chatgpt_developer_mode: ClientSetupPayloadResponse
    generic_http: ClientSetupPayloadResponse
  }
}

const TABS = [
  { key: 'vs_code' as const, label: 'VS Code' },
  { key: 'cursor' as const, label: 'Cursor' },
  { key: 'generic_http' as const, label: 'Generic HTTP' },
  { key: 'chatgpt_developer_mode' as const, label: 'ChatGPT' },
]

export function ClientConfigDisplay({ clients }: Props) {
  return (
    <Tabs defaultValue="vs_code">
      <TabsList className="flex-wrap h-auto">
        {TABS.map((tab) => (
          <TabsTrigger key={tab.key} value={tab.key}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>

      {TABS.map((tab) => (
        <TabsContent key={tab.key} value={tab.key} className="mt-4">
          <ClientCard payload={clients[tab.key]} />
        </TabsContent>
      ))}
    </Tabs>
  )
}

function ClientCard({ payload }: { payload: ClientSetupPayloadResponse }) {
  const isReady = payload.status === 'ready'
  const badgeLabel = isReady ? 'Ready' : payload.status.replace(/_/g, ' ')

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">{payload.display_name}</CardTitle>
          <Badge variant={isReady ? 'default' : 'secondary'}>
            {badgeLabel}
          </Badge>
        </div>
        {payload.availability_reason && (
          <CardDescription>{payload.availability_reason}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!isReady ? (
          <p className="text-sm text-muted-foreground">{payload.availability_reason}</p>
        ) : (
          <>
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground font-medium">Config file</p>
              <code className="text-xs font-mono text-muted-foreground">
                {payload.config_path_hint}
              </code>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground font-medium">
                  Configuration snippet
                </p>
                <CopyButton text={payload.snippet} />
              </div>
              <pre className="overflow-x-auto rounded-md border bg-muted p-3 text-xs font-mono whitespace-pre-wrap break-all">
                {payload.snippet}
              </pre>
            </div>

            {payload.instructions.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground font-medium">Steps</p>
                <ol className="space-y-1 text-sm list-decimal list-inside">
                  {payload.instructions.map((step, i) => (
                    <li key={i} className="text-muted-foreground">
                      {step}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <div className="rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              <strong>Auth:</strong> {payload.api_key_handling}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
