import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardList, RefreshCw } from 'lucide-react'
import { listAuditLog } from '@/api/audit'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatDateTime } from '@/lib/formatters'

function statusVariant(code: number): 'success' | 'error' | 'warning' | 'secondary' {
  if (code < 300) return 'success'
  if (code < 400) return 'secondary'
  if (code < 500) return 'warning'
  return 'error'
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'text-blue-400',
  POST: 'text-emerald-400',
  PATCH: 'text-amber-400',
  PUT: 'text-amber-400',
  DELETE: 'text-red-400',
}

export default function AuditLogPage() {
  const [resourceType, setResourceType] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['audit-log', resourceType],
    queryFn: () => listAuditLog({ resource_type: resourceType || undefined, limit: 100 }),
    refetchInterval: 30_000,
  })

  const RESOURCE_TYPES = ['agent', 'memory', 'action', 'session', 'episode', 'webhook', 'api_key']

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Audit Log</h1>
          <p className="text-sm text-muted-foreground">
            All API activity for this tenant · {data?.items.length ?? 0} entries
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={() => void refetch()}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setResourceType('')}
          className={`rounded-full border px-3 py-1 text-xs transition-colors ${
            resourceType === ''
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border text-muted-foreground hover:border-primary/50'
          }`}
        >
          All
        </button>
        {RESOURCE_TYPES.map((rt) => (
          <button
            key={rt}
            type="button"
            onClick={() => setResourceType(rt)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              resourceType === rt
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:border-primary/50'
            }`}
          >
            {rt}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12" />)}
        </div>
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState icon={ClipboardList} title="No audit entries" description="API activity will appear here." />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Method</TableHead>
                <TableHead>Path</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Resource</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.items.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell>
                    <span className={`font-mono text-xs font-medium ${METHOD_COLORS[entry.method] ?? 'text-foreground'}`}>
                      {entry.method}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground max-w-xs truncate">
                    {entry.path}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(entry.status_code)}>
                      {entry.status_code}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {entry.resource_type
                      ? `${entry.resource_type}${entry.resource_id ? ` ${entry.resource_id.slice(0, 8)}…` : ''}`
                      : '—'}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {entry.actor_key_name ?? entry.api_key_id?.slice(0, 8) ?? '—'}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatDateTime(entry.timestamp)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
