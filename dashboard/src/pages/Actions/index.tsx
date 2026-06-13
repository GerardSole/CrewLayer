import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import { listAgents } from '@/api/agents'
import { listActions, getActionStats } from '@/api/actions'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatDuration, formatDateTime, truncate } from '@/lib/formatters'
import type { ActionStatus } from '@/types/api'

const STATUS_VARIANT: Record<ActionStatus, 'success' | 'error' | 'warning' | 'secondary'> = {
  success: 'success',
  error: 'error',
  timeout: 'warning',
  pending: 'secondary',
}

const STATUS_FILTERS: Array<{ label: string; value: ActionStatus | '' }> = [
  { label: 'All', value: '' },
  { label: 'Success', value: 'success' },
  { label: 'Error', value: 'error' },
  { label: 'Timeout', value: 'timeout' },
]

export default function ActionsPage() {
  const [agentId, setAgentId] = useState('')
  const [statusFilter, setStatusFilter] = useState<ActionStatus | ''>('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => listAgents(),
  })

  const { data: stats } = useQuery({
    queryKey: ['action-stats', agentId],
    queryFn: () => getActionStats(agentId),
    enabled: !!agentId,
  })

  const { data: actions, isLoading, refetch } = useQuery({
    queryKey: ['actions', agentId, statusFilter],
    queryFn: () => listActions(agentId, { status: statusFilter || undefined, limit: 50 }),
    enabled: !!agentId,
  })

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Actions</h1>
        <p className="text-sm text-muted-foreground">Tool call history and stats</p>
      </div>

      {/* Agent selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">
          Select agent:
        </label>
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">— choose an agent —</option>
          {(agents ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      {agentId && (
        <>
          {/* Stats row */}
          {stats && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Total</p>
                  <p className="text-2xl font-bold">{stats.total_actions}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Error rate</p>
                  <p className={`text-2xl font-bold ${stats.error_rate > 0.2 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {(stats.error_rate * 100).toFixed(1)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Avg duration</p>
                  <p className="text-2xl font-bold">{formatDuration(stats.avg_duration_ms)}</p>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Filter + refresh */}
          <div className="flex flex-wrap gap-2 items-center">
            {STATUS_FILTERS.map(({ label, value }) => (
              <Button
                key={value}
                variant={statusFilter === value ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setStatusFilter(value)}
              >
                {label}
              </Button>
            ))}
            <Button variant="ghost" size="icon" onClick={() => void refetch()} className="ml-auto">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : (actions?.items.length ?? 0) === 0 ? (
            <EmptyState icon={Activity} title="No actions found" description="Actions will appear here as agents run tools." />
          ) : (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tool</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Timestamp</TableHead>
                    <TableHead className="w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {actions?.items.map((action) => (
                    <>
                      <TableRow
                        key={action.id}
                        className="cursor-pointer"
                        onClick={() => setExpanded(expanded === action.id ? null : action.id)}
                      >
                        <TableCell className="font-mono text-sm">{action.tool_name}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[action.status]} className="capitalize">
                            {action.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {action.duration_ms ? formatDuration(action.duration_ms) : '—'}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {formatDateTime(action.timestamp)}
                        </TableCell>
                        <TableCell>
                          {expanded === action.id ? (
                            <ChevronUp className="h-4 w-4 text-muted-foreground" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-muted-foreground" />
                          )}
                        </TableCell>
                      </TableRow>
                      {expanded === action.id && (
                        <TableRow key={`${action.id}-detail`}>
                          <TableCell colSpan={5} className="bg-muted/30">
                            <div className="grid gap-3 py-2 sm:grid-cols-2">
                              <div>
                                <p className="mb-1 text-xs font-medium text-muted-foreground">Input</p>
                                <pre className="rounded bg-muted p-2 text-xs overflow-auto max-h-32">
                                  {JSON.stringify(action.input_params, null, 2)}
                                </pre>
                              </div>
                              <div>
                                <p className="mb-1 text-xs font-medium text-muted-foreground">
                                  {action.status === 'error' ? 'Error' : 'Output'}
                                </p>
                                <pre className="rounded bg-muted p-2 text-xs overflow-auto max-h-32">
                                  {action.error_msg
                                    ? action.error_msg
                                    : JSON.stringify(action.output_result, null, 2)}
                                </pre>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}

          {/* By-tool breakdown */}
          {stats && stats.by_tool.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">By Tool</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tool</TableHead>
                      <TableHead>Calls</TableHead>
                      <TableHead>Avg duration</TableHead>
                      <TableHead>Error rate</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stats.by_tool
                      .sort((a, b) => b.count - a.count)
                      .map((t) => (
                        <TableRow key={t.tool_name}>
                          <TableCell className="font-mono text-sm">{t.tool_name}</TableCell>
                          <TableCell>{t.count}</TableCell>
                          <TableCell className="text-muted-foreground">
                            {formatDuration(t.avg_duration_ms)}
                          </TableCell>
                          <TableCell>
                            <span className={t.error_rate > 0.2 ? 'text-red-400' : 'text-emerald-400'}>
                              {(t.error_rate * 100).toFixed(1)}%
                            </span>
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {!agentId && (
        <EmptyState
          icon={Activity}
          title="Select an agent"
          description="Choose an agent above to view its action history."
        />
      )}
    </div>
  )
}
