export default function PublicLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-muted/20 p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold tracking-tight">MCP Database Agent</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Query your database with plain English
          </p>
        </div>
        {children}
      </div>
    </div>
  )
}
