import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Search, Trash2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, deleteAgent } from '@/api/agents'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'
import type { AgentStatus } from '@/types/api'

const STATUS_VARIANT: Record<AgentStatus, 'success' | 'warning' | 'error'> = {
  idle: 'success',
  working: 'warning',
  error: 'error',
}

const FILTERS: Array<{ label: string; value: AgentStatus | '' }> = [
  { label: 'All', value: '' },
  { label: 'Idle', value: 'idle' },
  { label: 'Working', value: 'working' },
  { label: 'Error', value: 'error' },
]

export default function AgentsPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<AgentStatus | ''>('')

  const { data = [], isLoading, refetch } = useQuery({
    queryKey: ['agents', { status: statusFilter || undefined }],
    queryFn: () => listAgents({ status: statusFilter || undefined }),
  })

  const deleteMut = useMutation({
    mutationFn: deleteAgent,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent deleted')
    },
    onError: () => toast.error('Failed to delete agent'),
  })

  const filtered = data.filter((a) =>
    a.name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
          <p className="text-sm text-muted-foreground">
            {data.length} agent{data.length !== 1 ? 's' : ''} in this tenant
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => toast.info('Use the CLI or SDK to create agents')}
        >
          + New Agent
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative w-64">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex gap-1.5">
          {FILTERS.map(({ label, value }) => (
            <Button
              key={value}
              variant={statusFilter === value ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setStatusFilter(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <Button variant="ghost" size="icon" onClick={() => void refetch()} title="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* List */}
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Bot}
          title={search ? 'No agents match your search' : 'No agents yet'}
          description={search ? 'Try a different search term.' : 'Create an agent with the CLI or SDK.'}
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((agent) => (
            <Card key={agent.id} className="hover:bg-accent/20 transition-colors">
              <CardContent className="flex items-center justify-between p-4">
                <div className="flex items-center gap-4 min-w-0">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <Bot className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{agent.name}</span>
                      <Badge variant={STATUS_VARIANT[agent.status]} className="capitalize shrink-0">
                        {agent.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                      <span className="font-mono">{agent.id.slice(0, 8)}…</span>
                      <span>·</span>
                      <span>{formatRelativeTime(agent.status_updated_at)}</span>
                      {agent.tags.length > 0 && (
                        <>
                          <span>·</span>
                          <div className="flex gap-1">
                            {agent.tags.slice(0, 3).map((t) => (
                              <span key={t} className="rounded bg-muted px-1.5 py-0.5">{t}</span>
                            ))}
                            {agent.tags.length > 3 && (
                              <span>+{agent.tags.length - 3}</span>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                  disabled={deleteMut.isPending}
                  onClick={() => {
                    if (confirm(`Delete agent "${agent.name}"? This cannot be undone.`)) {
                      deleteMut.mutate(agent.id)
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
