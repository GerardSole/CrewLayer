import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agents'
import { listPromptVersions, activatePromptVersion } from '@/api/prompts'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'

export default function PromptsPage() {
  const qc = useQueryClient()
  const [agentId, setAgentId] = useState('')

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => listAgents(),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['prompts', agentId],
    queryFn: () => listPromptVersions(agentId),
    enabled: !!agentId,
  })

  const activateMut = useMutation({
    mutationFn: (versionId: string) => activatePromptVersion(agentId, versionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['prompts', agentId] })
      toast.success('Prompt version activated')
    },
    onError: () => toast.error('Failed to activate prompt version'),
  })

  const sorted = [...(data?.items ?? [])].sort((a, b) => b.version - a.version)

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Prompts</h1>
        <p className="text-sm text-muted-foreground">Prompt version history per agent</p>
      </div>

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
        isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 w-full" />)}
          </div>
        ) : sorted.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No prompt versions"
            description="Create prompt versions using the API or SDK."
          />
        ) : (
          <div className="space-y-3">
            {sorted.map((pv) => (
              <Card
                key={pv.id}
                className={pv.is_active ? 'border-primary/40 bg-primary/5' : undefined}
              >
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium">v{pv.version}</span>
                        {pv.is_active && (
                          <Badge variant="success" className="gap-1">
                            <CheckCircle2 className="h-3 w-3" />
                            Active
                          </Badge>
                        )}
                        {pv.description && (
                          <span className="text-sm text-muted-foreground">— {pv.description}</span>
                        )}
                      </div>
                      <pre className="mt-2 max-h-32 overflow-auto rounded bg-muted p-3 text-xs whitespace-pre-wrap">
                        {pv.content}
                      </pre>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {formatRelativeTime(pv.created_at)}
                      </p>
                    </div>
                    {!pv.is_active && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => activateMut.mutate(pv.id)}
                        disabled={activateMut.isPending}
                        className="shrink-0"
                      >
                        Activate
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )
      )}

      {!agentId && (
        <EmptyState icon={FileText} title="Select an agent" description="Choose an agent above to view its prompt versions." />
      )}
    </div>
  )
}
