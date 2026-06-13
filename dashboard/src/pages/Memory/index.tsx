import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Brain, Search, Trash2, RefreshCw, Archive } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agents'
import { listMemories, recallMemories, deleteMemory } from '@/api/memory'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatImportance, formatRelativeTime, truncate } from '@/lib/formatters'

export default function MemoryPage() {
  const qc = useQueryClient()
  const [agentId, setAgentId] = useState('')
  const [search, setSearch] = useState('')
  const [recallQuery, setRecallQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => listAgents(),
  })

  const { data: memories, isLoading, refetch } = useQuery({
    queryKey: ['memories', agentId, includeArchived],
    queryFn: () => listMemories(agentId, { include_archived: includeArchived }),
    enabled: !!agentId,
  })

  const { data: recallResults, isLoading: recalling, refetch: doRecall } = useQuery({
    queryKey: ['recall', agentId, recallQuery],
    queryFn: () => recallMemories(agentId, recallQuery),
    enabled: false,
  })

  const deleteMut = useMutation({
    mutationFn: ({ memId }: { memId: string }) => deleteMemory(agentId, memId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memories', agentId] })
      toast.success('Memory deleted')
    },
    onError: () => toast.error('Failed to delete memory'),
  })

  const filtered = (memories?.items ?? []).filter((m) =>
    m.content.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Memory</h1>
        <p className="text-sm text-muted-foreground">Browse and search agent memories</p>
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
          {/* Semantic recall */}
          <Card>
            <CardContent className="pt-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Semantic Recall
              </p>
              <div className="flex gap-2">
                <Input
                  placeholder="Enter a query to recall relevant memories…"
                  value={recallQuery}
                  onChange={(e) => setRecallQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && recallQuery && void doRecall()}
                  className="flex-1"
                />
                <Button
                  onClick={() => void doRecall()}
                  disabled={!recallQuery || recalling}
                  variant="secondary"
                >
                  <Search className="h-4 w-4" />
                  {recalling ? 'Searching…' : 'Recall'}
                </Button>
              </div>
              {recallResults && (
                <div className="mt-3 space-y-2">
                  {recallResults.results.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No results found.</p>
                  ) : (
                    recallResults.results.map((r) => (
                      <div key={r.id} className="rounded-md border border-border p-3">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="info" className="text-xs">
                            {(r.similarity * 100).toFixed(0)}% match
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            importance {formatImportance(r.importance)}
                          </span>
                        </div>
                        <p className="text-sm">{r.content}</p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* List controls */}
          <div className="flex flex-wrap gap-3 items-center">
            <div className="relative w-64">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Filter memories…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Button
              variant={includeArchived ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setIncludeArchived(!includeArchived)}
            >
              <Archive className="h-4 w-4" />
              {includeArchived ? 'Hide archived' : 'Show archived'}
            </Button>
            <Button variant="ghost" size="icon" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground ml-auto">
              {memories?.total ?? 0} total
            </span>
          </div>

          {/* Memory list */}
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full rounded-lg" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={Brain}
              title="No memories"
              description="Memories will appear here as agents interact."
            />
          ) : (
            <div className="space-y-2">
              {filtered.map((mem) => (
                <Card key={mem.id} className="hover:bg-accent/20 transition-colors">
                  <CardContent className="flex items-start justify-between gap-4 p-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm">{truncate(mem.content, 200)}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>{formatImportance(mem.importance)} importance</span>
                        <span>·</span>
                        <span>{mem.access_count} accesses</span>
                        <span>·</span>
                        <span>{formatRelativeTime(mem.created_at)}</span>
                        {mem.status === 'archived' && (
                          <Badge variant="secondary" className="text-xs">archived</Badge>
                        )}
                      </div>
                      {/* Importance bar */}
                      <div className="mt-2 h-1 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${Math.max(2, mem.importance * 100)}%` }}
                        />
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                      disabled={deleteMut.isPending}
                      onClick={() => {
                        if (confirm('Delete this memory?')) {
                          deleteMut.mutate({ memId: mem.id })
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
        </>
      )}

      {!agentId && (
        <EmptyState
          icon={Brain}
          title="Select an agent"
          description="Choose an agent above to browse its memories."
        />
      )}
    </div>
  )
}
