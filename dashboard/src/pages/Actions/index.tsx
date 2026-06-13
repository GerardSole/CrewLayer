import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Search,
  RefreshCw,
  ChevronRight,
  Copy,
  Check,
  Play,
  ThumbsUp,
  ThumbsDown,
  X,
  Activity,
  Wrench,
  Bot,
} from 'lucide-react'
import { toast } from 'sonner'

import { listAgents } from '@/api/agents'
import { listActions, getActionStats, createReplay } from '@/api/actions'
import { submitEvaluation } from '@/api/evaluations'
import { getStoredCredentials } from '@/hooks/useApiKey'
import { Sheet } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatDuration, formatDateTime, formatNumber } from '@/lib/formatters'
import type { Action, ActionStatus, Replay } from '@/types/api'

// ── Shared helpers (duplicated from ActionsTab for page-level independence) ───

const STATUS_VARIANT: Record<ActionStatus, 'success' | 'error' | 'warning' | 'secondary'> = {
  success: 'success',
  error: 'error',
  timeout: 'warning',
  pending: 'secondary',
}

const STATUS_BG: Record<ActionStatus, string> = {
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  timeout: 'bg-amber-400',
  pending: 'bg-zinc-400',
}

// ── JSON Viewer ────────────────────────────────────────────────────────────────

interface Token { type: string; value: string }

function tokenizeJson(json: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  while (i < json.length) {
    const c = json[i]
    if (c === '"') {
      let j = i + 1
      while (j < json.length) {
        if (json[j] === '\\') { j += 2; continue }
        if (json[j] === '"') { j++; break }
        j++
      }
      const str = json.slice(i, j)
      let k = j
      while (k < json.length && (json[k] === ' ' || json[k] === '\t')) k++
      tokens.push({ type: json[k] === ':' ? 'key' : 'string', value: str })
      i = j
    } else if (c === '-' || (c >= '0' && c <= '9')) {
      let j = i
      while (j < json.length && /[-0-9.eE+]/.test(json[j])) j++
      tokens.push({ type: 'number', value: json.slice(i, j) })
      i = j || i + 1
    } else if (json.startsWith('true', i)) { tokens.push({ type: 'boolean', value: 'true' }); i += 4
    } else if (json.startsWith('false', i)) { tokens.push({ type: 'boolean', value: 'false' }); i += 5
    } else if (json.startsWith('null', i)) { tokens.push({ type: 'null', value: 'null' }); i += 4
    } else if ('{[]}:,'.includes(c)) { tokens.push({ type: 'punct', value: c }); i++
    } else {
      let j = i
      while (j < json.length && /\s/.test(json[j])) j++
      tokens.push({ type: 'ws', value: json.slice(i, Math.max(j, i + 1)) })
      i = Math.max(j, i + 1)
    }
  }
  return tokens
}

const TC: Record<string, string> = {
  key: 'text-zinc-300', string: 'text-emerald-400', number: 'text-amber-400',
  boolean: 'text-amber-300', null: 'text-rose-400', punct: 'text-muted-foreground',
}

function JsonViewer({ value, maxH = 'max-h-52' }: { value: unknown; maxH?: string }) {
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(value, null, 2)
  const tokens = useMemo(() => tokenizeJson(json), [json])
  return (
    <div className="relative group">
      <pre className={`rounded-md border border-border bg-muted/30 p-3 text-xs font-mono overflow-auto leading-5 ${maxH}`}>
        {tokens.map((t, i) => <span key={i} className={TC[t.type] ?? ''}>{t.value}</span>)}
      </pre>
      <button
        type="button"
        onClick={() => { void navigator.clipboard.writeText(json); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1 rounded-md bg-background border border-border text-muted-foreground hover:text-foreground transition-all"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

// ── Evaluation form ────────────────────────────────────────────────────────────

function EvalForm({ agentId, actionId }: { agentId: string; actionId: string }) {
  const [thumbs, setThumbs] = useState<'up' | 'down' | null>(null)
  const [score, setScore] = useState(3)
  const [notes, setNotes] = useState('')
  const [done, setDone] = useState(false)

  const evalMut = useMutation({
    mutationFn: () =>
      submitEvaluation(agentId, actionId, {
        rating_thumbs: thumbs ?? undefined,
        rating_score: score,
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => { toast.success('Evaluation submitted'); setDone(true) },
    onError: () => toast.error('Evaluation failed'),
  })

  if (done) return <p className="text-xs text-emerald-400">Evaluation submitted ✓</p>

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {(['up', 'down'] as const).map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setThumbs(thumbs === t ? null : t)}
            className={`p-2 rounded-lg border transition-colors ${thumbs === t ? (t === 'up' ? 'border-emerald-400 bg-emerald-950/40 text-emerald-400' : 'border-red-400 bg-red-950/40 text-red-400') : 'border-border text-muted-foreground hover:text-foreground'}`}
          >
            {t === 'up' ? <ThumbsUp className="h-4 w-4" /> : <ThumbsDown className="h-4 w-4" />}
          </button>
        ))}
        <div className="flex-1 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Score:</span>
          <input type="range" min="1" max="5" step="1" value={score} onChange={e => setScore(Number(e.target.value))} className="flex-1 accent-primary" />
          <span className="text-xs font-bold font-mono w-4">{score}</span>
        </div>
      </div>
      <Textarea placeholder="Notes (optional)…" value={notes} onChange={e => setNotes(e.target.value)} rows={2} className="text-xs" />
      <Button size="sm" onClick={() => evalMut.mutate()} disabled={evalMut.isPending || (!thumbs && !notes.trim())} className="w-full">
        {evalMut.isPending ? 'Submitting…' : 'Submit Evaluation'}
      </Button>
    </div>
  )
}

// ── Replay SSE hook ────────────────────────────────────────────────────────────

function useReplaySSE(agentId: string, replayId: string | null, onAction: (a: Action) => void, onComplete: () => void) {
  useEffect(() => {
    if (!replayId) return
    const creds = getStoredCredentials()
    if (!creds) return
    const ctrl = new AbortController()

    async function go() {
      try {
        const res = await fetch(`${creds!.baseURL}/v1/agents/${agentId}/replays/${replayId}/stream`, {
          headers: { 'X-API-Key': creds!.apiKey }, signal: ctrl.signal,
        })
        if (!res.ok || !res.body) { onComplete(); return }
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = '', evt = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''
          for (const line of lines) {
            if (line.startsWith('event: ')) evt = line.slice(7).trim()
            else if (line.startsWith('data: ')) {
              try {
                const d = JSON.parse(line.slice(6)) as unknown
                if (evt === 'action') onAction(d as Action)
                else if (evt === 'completed') onComplete()
              } catch {}
              evt = ''
            }
          }
        }
        onComplete()
      } catch (e) {
        if (e instanceof Error && e.name !== 'AbortError') onComplete()
      }
    }
    void go()
    return () => ctrl.abort()
  }, [agentId, replayId])
}

// ── Inline Replay panel ────────────────────────────────────────────────────────

function ReplayPanel({ agentId, initialFrom, onClose }: { agentId: string; initialFrom?: string; onClose: () => void }) {
  const toLocal = (iso?: string) => iso ? new Date(iso).toISOString().slice(0, 16) : new Date().toISOString().slice(0, 16)
  const [fromTs, setFromTs] = useState(() => toLocal(initialFrom))
  const [toTs, setToTs] = useState(() => toLocal())
  const [speed, setSpeed] = useState(1)
  const [replayId, setReplayId] = useState<string | null>(null)
  const [replay, setReplay] = useState<Replay | null>(null)
  const [actions, setActions] = useState<Action[]>([])
  const [done, setDone] = useState(false)

  const createMut = useMutation({
    mutationFn: () => createReplay(agentId, new Date(fromTs).toISOString(), new Date(toTs).toISOString(), speed),
    onSuccess: r => { setReplay(r); setReplayId(r.id) },
    onError: () => toast.error('Failed to create replay'),
  })

  useReplaySSE(agentId, replayId, a => setActions(prev => [...prev, a]), () => setDone(true))

  const total = replay?.action_count ?? 0

  return (
    <div className="space-y-4">
      {!replayId ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><label className="text-xs font-medium">From</label><Input type="datetime-local" value={fromTs} onChange={e => setFromTs(e.target.value)} className="text-xs" /></div>
            <div className="space-y-1"><label className="text-xs font-medium">To</label><Input type="datetime-local" value={toTs} onChange={e => setToTs(e.target.value)} className="text-xs" /></div>
          </div>
          <div className="flex gap-2">
            {[1, 2, 5, 10].map(s => (
              <Button key={s} variant={speed === s ? 'secondary' : 'outline'} size="sm" onClick={() => setSpeed(s)} className="flex-1 text-xs">{s}×</Button>
            ))}
          </div>
          <Button className="w-full" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
            <Play className="h-4 w-4 mr-2" />{createMut.isPending ? 'Creating…' : 'Start Replay'}
          </Button>
        </>
      ) : (
        <>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{done ? 'Completed' : 'Running…'} {total > 0 && `— ${actions.length} / ${total}`}</span>
            <span>{speed}×</span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div className={`h-full rounded-full transition-all ${done ? 'bg-emerald-400' : 'bg-primary'}`} style={{ width: total > 0 ? `${(actions.length / total) * 100}%` : '0%' }} />
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {[...actions].reverse().map((a, i) => (
              <div key={a.id} className={`flex items-center gap-2 rounded p-1.5 text-xs ${i === 0 && !done ? 'bg-primary/10 animate-pulse' : 'bg-muted/30'}`}>
                <div className={`h-2 w-2 rounded-full shrink-0 ${STATUS_BG[a.status]}`} />
                <span className="font-mono font-medium truncate flex-1">{a.tool_name}</span>
                <Badge variant={STATUS_VARIANT[a.status]} className="text-[10px]">{a.status}</Badge>
              </div>
            ))}
          </div>
          {done && <Button variant="outline" className="w-full" onClick={() => { setReplayId(null); setReplay(null); setActions([]); setDone(false) }}>Start New Replay</Button>}
        </>
      )}
    </div>
  )
}

// ── Action Detail Drawer ──────────────────────────────────────────────────────

function GlobalActionDetail({ agentId, action, agentName, onClose }: {
  agentId: string
  action: Action | null
  agentName: string
  onClose: () => void
}) {
  const [showReplay, setShowReplay] = useState(false)

  return (
    <Sheet open={!!action} onClose={() => { onClose(); setShowReplay(false) }} title={action?.tool_name ?? ''} description={action ? `${agentName} · ${formatDateTime(action.timestamp)}` : undefined}>
      {action && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <Badge variant={STATUS_VARIANT[action.status]} className="capitalize">{action.status}</Badge>
            {action.duration_ms != null && <Badge variant="secondary" className="font-mono">{formatDuration(action.duration_ms)}</Badge>}
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Input</p>
            <JsonViewer value={action.input_params} maxH="max-h-48" />
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {action.status === 'error' && action.error_msg ? 'Error' : 'Output'}
            </p>
            {action.status === 'error' && action.error_msg ? (
              <div className="rounded-md border border-red-800/50 bg-red-950/30 p-3 text-xs font-mono text-red-300 max-h-48 overflow-auto">{action.error_msg}</div>
            ) : (
              <JsonViewer value={action.output_result} maxH="max-h-48" />
            )}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Evaluation</p>
            <EvalForm agentId={agentId} actionId={action.id} />
          </div>
          <Button variant="outline" className="w-full gap-2" onClick={() => setShowReplay(p => !p)}>
            <Play className="h-4 w-4" />
            {showReplay ? 'Hide Replay' : 'Start Replay from here'}
          </Button>
          {showReplay && <ReplayPanel agentId={agentId} initialFrom={action.timestamp} onClose={() => setShowReplay(false)} />}
        </div>
      )}
    </Sheet>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ActionsPage() {
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [statusFilter, setStatusFilter] = useState<ActionStatus | ''>('')
  const [sinceDate, setSinceDate] = useState('')
  const [untilDate, setUntilDate] = useState('')
  const [searchText, setSearchText] = useState('')
  const [toolFilter, setToolFilter] = useState<string[]>([])
  const [extraActions, setExtraActions] = useState<Action[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selectedAction, setSelectedAction] = useState<Action | null>(null)
  const [selectedActionAgent, setSelectedActionAgent] = useState<string>('')

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: listAgents,
    staleTime: 60_000,
  })

  const { data: stats } = useQuery({
    queryKey: ['action-stats', selectedAgentId],
    queryFn: () => getActionStats(selectedAgentId),
    enabled: !!selectedAgentId,
    staleTime: 60_000,
    retry: false,
  })

  const { data: page1, isLoading, refetch } = useQuery({
    queryKey: ['global-actions', selectedAgentId, statusFilter, sinceDate, untilDate],
    queryFn: () => {
      if (!selectedAgentId) return Promise.resolve({ items: [], count: 0, next_cursor: null })
      return listActions(selectedAgentId, {
        status: statusFilter || undefined,
        since: sinceDate ? new Date(sinceDate).toISOString() : undefined,
        until: untilDate ? new Date(untilDate).toISOString() : undefined,
        limit: 50,
      })
    },
    enabled: !!selectedAgentId,
    staleTime: 30_000,
  })

  useEffect(() => {
    setExtraActions([])
    setNextCursor(page1?.next_cursor ?? null)
  }, [page1?.items[0]?.id])

  const allLoaded = [...(page1?.items ?? []), ...extraActions]

  const allTools = useMemo(() => {
    const s = new Set<string>()
    allLoaded.forEach(a => s.add(a.tool_name))
    return [...s].sort()
  }, [allLoaded])

  const maxDuration = useMemo(
    () => Math.max(...allLoaded.map(a => a.duration_ms ?? 0), 1),
    [allLoaded],
  )

  const filtered = useMemo(() => {
    let list = allLoaded
    if (toolFilter.length > 0) list = list.filter(a => toolFilter.includes(a.tool_name))
    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter(a =>
        JSON.stringify(a.input_params).toLowerCase().includes(q) ||
        JSON.stringify(a.output_result).toLowerCase().includes(q),
      )
    }
    return list
  }, [allLoaded, toolFilter, searchText])

  const hasFilters = toolFilter.length > 0 || !!statusFilter || !!sinceDate || !!untilDate || !!searchText

  const clearFilters = () => { setToolFilter([]); setStatusFilter(''); setSinceDate(''); setUntilDate(''); setSearchText('') }

  async function loadMore() {
    if (!nextCursor || !selectedAgentId) return
    setLoadingMore(true)
    try {
      const res = await listActions(selectedAgentId, {
        status: statusFilter || undefined,
        since: sinceDate ? new Date(sinceDate).toISOString() : undefined,
        until: untilDate ? new Date(untilDate).toISOString() : undefined,
        limit: 50,
        cursor: nextCursor,
      })
      setExtraActions(prev => [...prev, ...res.items])
      setNextCursor(res.next_cursor ?? null)
    } catch {
      toast.error('Failed to load more')
    } finally {
      setLoadingMore(false)
    }
  }

  const agentName = agents.find(a => a.id === selectedAgentId)?.name ?? ''
  const agentForDetail = selectedAction ? (selectedActionAgent || selectedAgentId) : selectedAgentId

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-5 border-b border-border shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Actions</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Tool call history across all agents</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-5">
          {/* Agent selector + stats */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-muted-foreground" />
              <select
                value={selectedAgentId}
                onChange={e => { setSelectedAgentId(e.target.value); setExtraActions([]); setSelectedAction(null) }}
                className="h-9 rounded-md border border-border bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring min-w-[180px]"
              >
                <option value="">— Select agent —</option>
                {agents.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>

            {stats && (
              <div className="flex items-center gap-4 text-sm ml-4">
                <span>
                  <span className="text-muted-foreground">Total: </span>
                  <span className="font-semibold">{formatNumber(stats.total_actions)}</span>
                </span>
                <span>
                  <span className="text-muted-foreground">Success: </span>
                  <span className={`font-semibold ${(1 - stats.error_rate) >= 0.9 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {((1 - stats.error_rate) * 100).toFixed(1)}%
                  </span>
                </span>
                {stats.avg_duration_ms != null && (
                  <span>
                    <span className="text-muted-foreground">Avg latency: </span>
                    <span className="font-semibold">{formatDuration(stats.avg_duration_ms)}</span>
                  </span>
                )}
                {stats.by_tool[0] && (
                  <span>
                    <span className="text-muted-foreground">Top tool: </span>
                    <code className="font-semibold">{stats.by_tool[0].tool_name}</code>
                  </span>
                )}
              </div>
            )}
          </div>

          {!selectedAgentId ? (
            <EmptyState icon={Activity} title="Select an agent" description="Choose an agent above to view its action history." />
          ) : (
            <>
              {/* Filters */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative w-48">
                  <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input placeholder="Search params…" value={searchText} onChange={e => setSearchText(e.target.value)} className="pl-8 h-8 text-xs" />
                </div>

                {/* Tool multiselect */}
                {allTools.length > 0 && (
                  <div className="relative">
                    <Button
                      variant={toolFilter.length > 0 ? 'secondary' : 'outline'}
                      size="sm"
                      className="h-8 text-xs"
                      onClick={() => {
                        const el = document.getElementById('tool-filter-menu')
                        if (el) el.toggleAttribute('hidden')
                      }}
                    >
                      <Wrench className="h-3 w-3 mr-1" />
                      Tools {toolFilter.length > 0 && `(${toolFilter.length})`}
                    </Button>
                  </div>
                )}

                {(['', 'success', 'error', 'timeout'] as const).map(s => (
                  <Button key={s} variant={statusFilter === s ? 'secondary' : 'ghost'} size="sm" className="h-8 text-xs" onClick={() => setStatusFilter(s)}>
                    {s === '' ? 'All' : s}
                  </Button>
                ))}

                <Input type="date" value={sinceDate} onChange={e => setSinceDate(e.target.value)} className="h-8 text-xs w-32" />
                <span className="text-xs text-muted-foreground">–</span>
                <Input type="date" value={untilDate} onChange={e => setUntilDate(e.target.value)} className="h-8 text-xs w-32" />

                {hasFilters && (
                  <Button variant="ghost" size="sm" className="h-8 text-xs gap-1" onClick={clearFilters}>
                    <X className="h-3 w-3" />
                    Clear
                  </Button>
                )}

                <Button variant="ghost" size="icon" className="h-8 w-8 ml-auto" onClick={() => void refetch()}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              </div>

              {/* Tool filter (inline checkboxes) */}
              {allTools.length > 0 && toolFilter.length === 0 ? null : allTools.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {allTools.map(tool => (
                    <button
                      key={tool}
                      type="button"
                      onClick={() => setToolFilter(prev => prev.includes(tool) ? prev.filter(t => t !== tool) : [...prev, tool])}
                      className={`rounded-md px-2.5 py-1 text-xs font-mono border transition-colors ${toolFilter.includes(tool) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
                    >
                      {tool}
                    </button>
                  ))}
                </div>
              )}

              {/* Table */}
              {isLoading ? (
                <div className="space-y-1.5">
                  {[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-12 rounded-md" />)}
                </div>
              ) : filtered.length === 0 ? (
                <EmptyState icon={Activity} title={hasFilters ? 'No actions match your filters' : 'No actions yet'} description={hasFilters ? 'Adjust or clear the filters.' : 'Actions will appear here as the agent uses tools.'} action={hasFilters ? <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button> : undefined} />
              ) : (
                <>
                  <div className="rounded-lg border border-border overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/40">
                        <tr className="border-b border-border">
                          <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Timestamp</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Tool</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Status</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide w-40">Duration</th>
                          <th className="px-3 py-2 w-8" />
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map(action => (
                          <tr
                            key={action.id}
                            className="border-b border-border/50 hover:bg-accent/30 cursor-pointer transition-colors group"
                            onClick={() => {
                              setSelectedAction(action)
                              setSelectedActionAgent(selectedAgentId)
                            }}
                          >
                            <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">{formatDateTime(action.timestamp)}</td>
                            <td className="px-3 py-2.5"><code className="text-xs font-semibold">{action.tool_name}</code></td>
                            <td className="px-3 py-2.5">
                              <Badge variant={STATUS_VARIANT[action.status]} className="text-xs capitalize">{action.status}</Badge>
                            </td>
                            <td className="px-3 py-2.5">
                              {action.duration_ms != null ? (
                                <div className="flex items-center gap-2">
                                  <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
                                    <div className={`h-full rounded-full ${STATUS_BG[action.status]}`} style={{ width: `${(action.duration_ms / maxDuration) * 100}%` }} />
                                  </div>
                                  <span className="text-xs font-mono text-muted-foreground shrink-0 w-12 text-right">{formatDuration(action.duration_ms)}</span>
                                </div>
                              ) : <span className="text-xs text-muted-foreground">—</span>}
                            </td>
                            <td className="px-3 py-2.5">
                              <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {nextCursor && (
                    <div className="flex justify-center">
                      <Button variant="outline" size="sm" onClick={() => void loadMore()} disabled={loadingMore}>
                        {loadingMore ? 'Loading…' : 'Load more'}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* Action detail drawer */}
      <GlobalActionDetail
        agentId={agentForDetail}
        action={selectedAction}
        agentName={agentName}
        onClose={() => setSelectedAction(null)}
      />
    </div>
  )
}
