import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Key, Database, Cpu, LogOut, Shield, Trash2, Plus,
  Copy, Check, AlertTriangle, Download, Bot,
} from 'lucide-react'
import { toast } from 'sonner'
import { useNavigate } from 'react-router-dom'

import { getUsage } from '@/api/usage'
import { listApiKeys, createApiKey, revokeApiKey, clearCredentials, getBaseURL } from '@/api/auth'
import { listAgents } from '@/api/agents'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { formatRelativeTime, formatDate, formatNumber } from '@/lib/formatters'
import { STORAGE_KEYS } from '@/lib/constants'
import type { ApiKeyCreated } from '@/types/api'

const ALL_SCOPES = [
  'agents:read', 'agents:write',
  'memory:read', 'memory:write',
  'actions:read', 'actions:write',
  'context:read', 'context:write',
  'sessions:read', 'sessions:write',
]

const PLAN_VARIANT: Record<string, 'success' | 'info' | 'secondary'> = {
  free: 'secondary', pro: 'success', enterprise: 'info',
}

// ── Copy once key modal ───────────────────────────────────────────────────────

function KeyCreatedModal({ created, onClose }: { created: ApiKeyCreated; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(created.key)
    setCopied(true)
  }
  return (
    <Dialog open onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API Key Created</DialogTitle>
          <DialogDescription>Copy your key now — it won't be shown again.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="rounded-md border border-amber-500/30 bg-amber-950/20 p-3 flex gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-300">This key will only be shown once. Copy it now and store it securely.</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">API Key</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs font-mono break-all">{created.key}</code>
              <Button size="sm" variant="outline" onClick={copy} className="shrink-0">
                {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <Button className="w-full" onClick={onClose}>I've saved the key</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── New API Key modal ─────────────────────────────────────────────────────────

function NewKeyModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (k: ApiKeyCreated) => void
}) {
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [agentIds, setAgentIds] = useState<string[]>([])
  const [expiresAt, setExpiresAt] = useState('')

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: listAgents,
    staleTime: 60_000,
  })

  const createMut = useMutation({
    mutationFn: () =>
      createApiKey({
        name: name.trim(),
        scopes,
        agent_ids: agentIds,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      }),
    onSuccess: k => {
      toast.success('API key created')
      onCreated(k)
      setName(''); setScopes([]); setAgentIds([]); setExpiresAt('')
      onClose()
    },
    onError: () => toast.error('Failed to create API key'),
  })

  const toggleScope = (s: string) =>
    setScopes(p => p.includes(s) ? p.filter(x => x !== s) : [...p, s])
  const toggleAgent = (id: string) =>
    setAgentIds(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id])

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New API Key</DialogTitle>
          <DialogDescription>Configure scopes and restrictions for this API key.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Name *</label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. production-agent" />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Scopes</label>
            <p className="text-xs text-muted-foreground">Leave empty for full access.</p>
            <div className="grid grid-cols-2 gap-1.5">
              {ALL_SCOPES.map(s => (
                <label key={s} className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scopes.includes(s)}
                    onChange={() => toggleScope(s)}
                    className="accent-primary"
                  />
                  <code>{s}</code>
                </label>
              ))}
            </div>
          </div>

          {agents.length > 0 && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Restrict to Agents</label>
              <p className="text-xs text-muted-foreground">Leave empty to allow all agents.</p>
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {agents.map(a => (
                  <label key={a.id} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      checked={agentIds.includes(a.id)}
                      onChange={() => toggleAgent(a.id)}
                      className="accent-primary"
                    />
                    <span>{a.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Expires At</label>
            <Input type="date" value={expiresAt} onChange={e => setExpiresAt(e.target.value)} className="text-xs" />
          </div>

          <div className="flex gap-2 pt-1">
            <Button className="flex-1" disabled={!name.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? 'Creating…' : 'Create Key'}
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── API Keys table ────────────────────────────────────────────────────────────

function ApiKeysSection() {
  const qc = useQueryClient()
  const [newOpen, setNewOpen] = useState(false)
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null)

  const { data: keys = [], isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: listApiKeys,
    staleTime: 30_000,
  })

  const revokeMut = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      toast.success('Key revoked')
      void qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: () => toast.error('Failed to revoke key'),
  })

  const currentApiKey = localStorage.getItem(STORAGE_KEYS.API_KEY) ?? ''

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold flex items-center gap-2"><Key className="h-4 w-4" />API Keys</h2>
        <Button size="sm" variant="outline" onClick={() => setNewOpen(true)}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />New Key
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-1.5">{[0,1,2].map(i => <Skeleton key={i} className="h-14" />)}</div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-muted-foreground">No API keys.</p>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b border-border">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Scopes</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Last Used</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Expires</th>
                  <th className="px-3 py-2 w-16" />
                </tr>
              </thead>
              <tbody>
                {keys.map(k => {
                  const isCurrent = currentApiKey.includes(k.id.replace(/-/g, ''))
                  return (
                    <tr key={k.id} className="border-b border-border/50">
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{k.name}</span>
                          {isCurrent && <Badge variant="success" className="text-[10px] px-1">current</Badge>}
                        </div>
                        <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{k.id.slice(0, 12)}…</p>
                      </td>
                      <td className="px-3 py-2.5">
                        {k.scopes.length === 0
                          ? <span className="text-xs text-muted-foreground">full access</span>
                          : <div className="flex flex-wrap gap-0.5">{k.scopes.map(s => <code key={s} className="rounded bg-muted px-1 py-0.5 text-[10px]">{s}</code>)}</div>
                        }
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">
                        {k.last_used_at ? formatRelativeTime(k.last_used_at) : 'Never'}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">
                        {k.expires_at ? formatDate(k.expires_at) : 'Never'}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {!isCurrent && (
                          <Button
                            variant="ghost" size="sm" className="h-7 text-xs text-destructive hover:text-destructive"
                            onClick={() => { if (confirm(`Revoke key "${k.name}"?`)) revokeMut.mutate(k.id) }}
                            disabled={revokeMut.isPending}
                          >
                            <Trash2 className="h-3 w-3 mr-1" />Revoke
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <NewKeyModal open={newOpen} onClose={() => setNewOpen(false)} onCreated={setCreatedKey} />
      {createdKey && <KeyCreatedModal created={createdKey} onClose={() => setCreatedKey(null)} />}
    </div>
  )
}

// ── Usage bar ─────────────────────────────────────────────────────────────────

function UsageBar({ used, limit, label }: { used: number; limit?: number; label: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0
  const color = pct > 90 ? 'bg-red-400' : pct > 70 ? 'bg-amber-400' : 'bg-primary'
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">{formatNumber(used)}{limit ? ` / ${formatNumber(limit)}` : ''}</span>
      </div>
      {limit && (
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const navigate = useNavigate()
  const baseURL = getBaseURL()
  const apiKey = localStorage.getItem(STORAGE_KEYS.API_KEY) ?? ''

  const { data: usage } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
    staleTime: 60_000,
  })

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: listAgents,
    staleTime: 60_000,
  })

  const handleDisconnect = () => {
    clearCredentials()
    toast.success('Disconnected')
    navigate('/login')
  }

  const exportData = () => {
    const payload = {
      exported_at: new Date().toISOString(),
      tenant_id: usage?.tenant_id,
      plan: usage?.plan,
      agents: agents.map(a => ({ id: a.id, name: a.name, description: a.description, tags: a.tags, config: a.config })),
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `crewlayer-export-${new Date().toISOString().split('T')[0]}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('Export downloaded')
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-5 border-b border-border shrink-0">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Manage your CrewLayer instance</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl space-y-8">

          {/* API Keys */}
          <ApiKeysSection />

          <Separator />

          {/* Tenant */}
          <div className="space-y-3">
            <h2 className="text-base font-semibold flex items-center gap-2"><Database className="h-4 w-4" />Tenant</h2>
            <Card>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Instance URL</p>
                    <code className="text-sm">{baseURL}</code>
                  </div>
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">API Key (current)</p>
                    <code className="text-sm">{apiKey.slice(0, 12)}{'•'.repeat(Math.max(0, apiKey.length - 12))}</code>
                  </div>
                </div>
                {usage && (
                  <>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-muted-foreground">Tenant ID</p>
                        <code className="text-xs font-mono text-muted-foreground">{usage.tenant_id}</code>
                      </div>
                      <Badge variant={PLAN_VARIANT[usage.plan] ?? 'secondary'} className="capitalize">{usage.plan}</Badge>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Plan & Usage */}
          {usage && (
            <>
              <Separator />
              <div className="space-y-3">
                <h2 className="text-base font-semibold flex items-center gap-2"><Cpu className="h-4 w-4" />Usage</h2>
                <Card>
                  <CardContent className="p-4 space-y-4">
                    <div className="flex items-center gap-2 text-sm">
                      <Bot className="h-4 w-4 text-muted-foreground" />
                      <span className="text-muted-foreground">Agents:</span>
                      <span className="font-semibold">{agents.length}</span>
                    </div>
                    <UsageBar used={usage.usage.requests_today} limit={usage.limits.per_day ?? undefined} label="API requests today" />
                    <UsageBar used={usage.usage.requests_this_minute} limit={usage.limits.per_minute ?? undefined} label="API requests / min" />
                    <UsageBar used={usage.usage.embedding_requests_this_minute} limit={usage.limits.embedding_per_minute ?? undefined} label="Embedding requests / min" />
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          {/* Memory Decay (read-only display) */}
          <Separator />
          <div className="space-y-3">
            <h2 className="text-base font-semibold flex items-center gap-2"><Shield className="h-4 w-4" />Memory Decay</h2>
            <Card>
              <CardContent className="p-4 space-y-3">
                <p className="text-xs text-muted-foreground">Memory decay settings are configured per-tenant on the server. Contact your administrator to change these values.</p>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="space-y-0.5">
                    <p className="text-xs text-muted-foreground">Decay enabled</p>
                    <p className="font-medium">Configured server-side</p>
                  </div>
                  <div className="space-y-0.5">
                    <p className="text-xs text-muted-foreground">Schedule</p>
                    <p className="font-medium">Daily at 03:00 UTC</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Danger Zone */}
          <Separator />
          <div className="space-y-3">
            <h2 className="text-base font-semibold flex items-center gap-2 text-destructive"><AlertTriangle className="h-4 w-4" />Danger Zone</h2>
            <Card className="border-destructive/30">
              <CardContent className="p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">Export tenant data</p>
                    <p className="text-xs text-muted-foreground">Download all agents and configuration as JSON.</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={exportData} className="gap-1.5">
                    <Download className="h-3.5 w-3.5" />Export
                  </Button>
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">Disconnect</p>
                    <p className="text-xs text-muted-foreground">Removes stored credentials from this browser.</p>
                  </div>
                  <Button variant="destructive" size="sm" onClick={handleDisconnect} className="gap-1.5">
                    <LogOut className="h-3.5 w-3.5" />Disconnect
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

        </div>
      </div>
    </div>
  )
}
