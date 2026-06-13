import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Webhook, Plus, Trash2, RefreshCw, Play, ChevronRight,
  ChevronDown, Copy, Check, ToggleLeft, ToggleRight, X,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  listWebhooks, createWebhook, deleteWebhook, toggleWebhook,
  listDeliveries, testWebhook,
} from '@/api/webhooks'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime, formatDateTime } from '@/lib/formatters'
import type { WebhookEndpoint, WebhookDelivery } from '@/types/api'

const AVAILABLE_EVENTS = [
  'agent.status_changed',
  'memory.saved',
  'action.logged',
  'action.error',
  'episode.completed',
  'anomaly.detected',
]

// ── New Webhook Modal ─────────────────────────────────────────────────────────

function NewWebhookModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>([])

  const createMut = useMutation({
    mutationFn: () => createWebhook({ url: url.trim(), events: selectedEvents, secret: secret.trim() }),
    onSuccess: () => {
      toast.success('Webhook registered')
      void qc.invalidateQueries({ queryKey: ['webhooks'] })
      setUrl(''); setSecret(''); setSelectedEvents([])
      onClose()
    },
    onError: () => toast.error('Failed to register webhook'),
  })

  const toggle = (ev: string) =>
    setSelectedEvents(p => p.includes(ev) ? p.filter(e => e !== ev) : [...p, ev])

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Webhook Endpoint</DialogTitle>
          <DialogDescription>Register a URL to receive real-time event notifications.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">URL *</label>
            <Input placeholder="https://your-server.com/webhook" value={url} onChange={e => setUrl(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Secret</label>
            <Input placeholder="Optional signing secret" value={secret} onChange={e => setSecret(e.target.value)} type="password" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Events *</label>
            <div className="flex flex-wrap gap-1.5">
              {AVAILABLE_EVENTS.map(ev => (
                <button
                  key={ev}
                  type="button"
                  onClick={() => toggle(ev)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${selectedEvents.includes(ev) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/50'}`}
                >
                  {ev}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2 pt-1">
            <Button
              className="flex-1"
              disabled={!url.trim() || selectedEvents.length === 0 || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {createMut.isPending ? 'Registering…' : 'Register Webhook'}
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Delivery payload viewer ───────────────────────────────────────────────────

function DeliveryRow({ d }: { d: WebhookDelivery }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = () => {
    void navigator.clipboard.writeText(JSON.stringify(d.payload, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const statusColor = d.response_status != null
    ? d.response_status < 300 ? 'text-emerald-400' : d.response_status < 500 ? 'text-amber-400' : 'text-red-400'
    : d.status === 'failed' ? 'text-red-400' : 'text-muted-foreground'

  return (
    <div className="border-b border-border/50 last:border-0">
      <button
        type="button"
        className="w-full flex items-center gap-3 px-4 py-3 text-sm hover:bg-accent/20 transition-colors"
        onClick={() => setExpanded(p => !p)}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
        <span className="flex-1 text-left font-mono text-xs text-muted-foreground">{d.event}</span>
        <span className={`font-mono text-xs font-medium ${statusColor}`}>
          {d.response_status ?? d.status}
        </span>
        <span className="text-xs text-muted-foreground shrink-0">
          {d.last_attempt_at ? formatRelativeTime(d.last_attempt_at) : '—'}
        </span>
        <Badge variant="secondary" className="text-[10px] shrink-0">{d.attempts} attempt{d.attempts !== 1 ? 's' : ''}</Badge>
      </button>
      {expanded && (
        <div className="relative mx-4 mb-3">
          <pre className="rounded-md border border-border bg-muted/30 p-3 text-xs font-mono overflow-auto max-h-48">
            {JSON.stringify(d.payload, null, 2)}
          </pre>
          <button
            type="button"
            onClick={copy}
            className="absolute top-2 right-2 p-1 rounded-md bg-background border border-border text-muted-foreground hover:text-foreground transition-all"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Delivery History Sheet ────────────────────────────────────────────────────

function DeliverySheet({ webhook, onClose }: { webhook: WebhookEndpoint; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['deliveries', webhook.id],
    queryFn: () => listDeliveries(webhook.id),
    staleTime: 30_000,
    retry: false,
  })

  return (
    <Sheet open title="Delivery History" description={webhook.url} onClose={onClose}>
      {isLoading ? (
        <div className="space-y-2">{[0,1,2,3].map(i => <Skeleton key={i} className="h-12" />)}</div>
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState icon={Webhook} title="No deliveries yet" description="Deliveries will appear here after events fire." />
      ) : (
        <div className="rounded-md border border-border overflow-hidden">
          {data!.items.map(d => <DeliveryRow key={d.id} d={d} />)}
        </div>
      )}
    </Sheet>
  )
}

// ── Webhook Card ──────────────────────────────────────────────────────────────

function WebhookCard({ wh }: { wh: WebhookEndpoint }) {
  const qc = useQueryClient()
  const [showDeliveries, setShowDeliveries] = useState(false)

  const toggleMut = useMutation({
    mutationFn: () => toggleWebhook(wh.id, !wh.active),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['webhooks'] })
      toast.success(wh.active ? 'Webhook disabled' : 'Webhook enabled')
    },
    onError: () => toast.error('Failed to toggle webhook'),
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteWebhook(wh.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['webhooks'] })
      toast.success('Webhook deleted')
    },
    onError: () => toast.error('Failed to delete webhook'),
  })

  const testMut = useMutation({
    mutationFn: () => testWebhook(wh.id),
    onSuccess: () => toast.success('Test event sent'),
    onError: () => toast.error('Test failed'),
  })

  return (
    <>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <div className="flex-1 min-w-0 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <code className="text-sm font-medium truncate max-w-md">{wh.url}</code>
                <Badge variant={wh.active ? 'success' : 'secondary'} className="text-xs shrink-0">
                  {wh.active ? 'active' : 'inactive'}
                </Badge>
              </div>
              <div className="flex flex-wrap gap-1">
                {wh.events.map(ev => (
                  <span key={ev} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{ev}</span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">Created {formatRelativeTime(wh.created_at)}</p>
            </div>

            <div className="flex items-center gap-1 shrink-0">
              <button
                type="button"
                title={wh.active ? 'Disable' : 'Enable'}
                onClick={() => toggleMut.mutate()}
                disabled={toggleMut.isPending}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
              >
                {wh.active
                  ? <ToggleRight className="h-5 w-5 text-emerald-400" />
                  : <ToggleLeft className="h-5 w-5" />}
              </button>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" title="Delivery history" onClick={() => setShowDeliveries(true)}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" title="Send test event" onClick={() => testMut.mutate()} disabled={testMut.isPending}>
                <Play className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                title="Delete"
                onClick={() => { if (confirm('Delete this webhook?')) deleteMut.mutate() }}
                disabled={deleteMut.isPending}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {showDeliveries && <DeliverySheet webhook={wh} onClose={() => setShowDeliveries(false)} />}
    </>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function WebhooksPage() {
  const [newOpen, setNewOpen] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['webhooks'],
    queryFn: listWebhooks,
    staleTime: 30_000,
  })

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-start justify-between px-6 py-5 border-b border-border shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Webhooks</h1>
          <p className="text-sm text-muted-foreground mt-0.5">HTTP callbacks for CrewLayer events</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => void refetch()}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={() => setNewOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />New Webhook
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="space-y-2">{[0,1,2].map(i => <Skeleton key={i} className="h-24" />)}</div>
        ) : (data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={Webhook}
            title="No webhooks yet"
            description="Register an endpoint to receive real-time events from CrewLayer."
            action={<Button size="sm" onClick={() => setNewOpen(true)}>Register first webhook</Button>}
          />
        ) : (
          <div className="space-y-2">
            {data!.map(wh => <WebhookCard key={wh.id} wh={wh} />)}
          </div>
        )}
      </div>

      <NewWebhookModal open={newOpen} onClose={() => setNewOpen(false)} />
    </div>
  )
}
