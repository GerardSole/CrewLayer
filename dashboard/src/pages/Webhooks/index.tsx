import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Webhook, Plus, Trash2, RefreshCw, Play } from 'lucide-react'
import { toast } from 'sonner'
import { listWebhooks, createWebhook, deleteWebhook, testWebhook } from '@/api/webhooks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'

const AVAILABLE_EVENTS = [
  'agent.status_changed',
  'memory.saved',
  'action.logged',
  'action.error',
  'episode.completed',
  'anomaly.detected',
]

export default function WebhooksPage() {
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [url, setUrl] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>([])

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['webhooks'],
    queryFn: listWebhooks,
  })

  const createMut = useMutation({
    mutationFn: () => createWebhook({ url, events: selectedEvents }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['webhooks'] })
      setUrl('')
      setSelectedEvents([])
      setShowAdd(false)
      toast.success('Webhook registered')
    },
    onError: () => toast.error('Failed to create webhook'),
  })

  const deleteMut = useMutation({
    mutationFn: deleteWebhook,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['webhooks'] })
      toast.success('Webhook deleted')
    },
    onError: () => toast.error('Failed to delete webhook'),
  })

  const testMut = useMutation({
    mutationFn: testWebhook,
    onSuccess: () => toast.success('Test event sent'),
    onError: () => toast.error('Test failed'),
  })

  const toggleEvent = (ev: string) => {
    setSelectedEvents((prev) =>
      prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev],
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Webhooks</h1>
          <p className="text-sm text-muted-foreground">HTTP callbacks for CrewLayer events</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="icon" onClick={() => void refetch()}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={() => setShowAdd(!showAdd)}>
            <Plus className="h-4 w-4" /> Add webhook
          </Button>
        </div>
      </div>

      {/* Create form */}
      {showAdd && (
        <Card>
          <CardContent className="space-y-4 p-4">
            <p className="text-sm font-medium">New webhook endpoint</p>
            <Input
              placeholder="https://your-server.com/webhook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <div>
              <p className="mb-2 text-xs text-muted-foreground">Select events:</p>
              <div className="flex flex-wrap gap-2">
                {AVAILABLE_EVENTS.map((ev) => (
                  <button
                    key={ev}
                    type="button"
                    onClick={() => toggleEvent(ev)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      selectedEvents.includes(ev)
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:border-primary/50'
                    }`}
                  >
                    {ev}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => createMut.mutate()}
                disabled={!url || selectedEvents.length === 0 || createMut.isPending}
              >
                Register
              </Button>
              <Button variant="ghost" onClick={() => setShowAdd(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* List */}
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}
        </div>
      ) : (data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={Webhook}
          title="No webhooks yet"
          description="Register an endpoint to receive real-time events."
        />
      ) : (
        <div className="space-y-2">
          {data?.map((wh) => (
            <Card key={wh.id}>
              <CardContent className="flex items-start justify-between gap-4 p-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-sm font-medium truncate">{wh.url}</code>
                    <Badge variant={wh.is_active ? 'success' : 'secondary'}>
                      {wh.is_active ? 'active' : 'inactive'}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-1 mb-1">
                    {wh.events.map((ev) => (
                      <span key={ev} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                        {ev}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Created {formatRelativeTime(wh.created_at)}
                    {wh.last_triggered_at && ` · last fired ${formatRelativeTime(wh.last_triggered_at)}`}
                  </p>
                </div>
                <div className="flex gap-1 shrink-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground"
                    disabled={testMut.isPending}
                    onClick={() => testMut.mutate(wh.id)}
                    title="Send test event"
                  >
                    <Play className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    disabled={deleteMut.isPending}
                    onClick={() => {
                      if (confirm('Delete this webhook?')) deleteMut.mutate(wh.id)
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
