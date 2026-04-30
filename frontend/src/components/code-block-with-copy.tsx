'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CodeBlockWithCopyProps {
  code: string
  inline?: boolean
  className?: string
}

export function CodeBlockWithCopy({ code, inline = false, className }: CodeBlockWithCopyProps) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code)
    } catch {
      const el = document.createElement('textarea')
      el.value = code
      el.style.position = 'fixed'
      el.style.opacity = '0'
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (inline) {
    return (
      <div className={cn('flex items-center gap-2', className)}>
        <code className="flex-1 rounded-xl border bg-muted/70 px-3 py-2 text-sm font-mono truncate">
          {code}
        </code>
        <button
          onClick={handleCopy}
          className="shrink-0 rounded-xl border bg-background px-3 py-2 text-sm font-medium hover:bg-muted transition-colors flex items-center gap-1.5"
          title="Copy to clipboard"
        >
          {copied ? (
            <><Check className="w-3.5 h-3.5 text-emerald-500" /><span className="text-emerald-600">Copied</span></>
          ) : (
            <><Copy className="w-3.5 h-3.5" /><span>Copy</span></>
          )}
        </button>
      </div>
    )
  }

  return (
    <div className={cn('relative rounded-2xl border bg-muted/70 shadow-sm', className)}>
      <pre className="overflow-x-auto p-3 pr-10 text-xs font-mono whitespace-pre-wrap break-all leading-relaxed">
        {code}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1.5 rounded-lg hover:bg-background transition-colors"
        title="Copy to clipboard"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-green-500" />
        ) : (
          <Copy className="w-3.5 h-3.5 text-muted-foreground" />
        )}
      </button>
    </div>
  )
}
