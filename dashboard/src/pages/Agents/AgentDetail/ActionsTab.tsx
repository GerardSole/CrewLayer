import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Search,
  Copy,
  Check,
  ChevronRight,
  Play,
  Pause,
  Square,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
  X,
  Zap,
  Activity,
  Clock,
  AlertTriangle,
  Wrench,
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { subDays, format, differenceInDays } from 'date-fns'
import { toast } from 'sonner'

import { listActions, getActionStats, createReplay } from '@/api/actions'
import { submitEvaluation } from '@/api/evaluations'
import { getStoredCredentials } from '@/hooks/useApiKey'
import { Sheet } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatDuration, formatDateTime, formatNumber } from '@/lib/formatters'
import type { Action, ActionStatus, Replay } from '@/types/api'

// ── JSON Tokenizer ────────────────────────────────────────────────────────────

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
    } else if (json.startsWith('true', i)) {
      tokens.push({ type: 'boolean', value: 'true' }); i += 4
    } else if (json.startsWith('false', i)) {
      tokens.push({ type: 'boolean', value: 'false' }); i += 5
    } else if (json.startsWith('null', i)) {
      tokens.push({ type: 'null', value: 'null' }); i += 4
    } else if ('{[]}:,'.includes(c)) {
      tokens.push({ type: 'punct', value: c }); i++
    } else {
      let j = i
      while (j < json.length && /\s/.test(json[j])) j++
      tokens.push({ type: 'ws', value: json.slice(i, Math.max(j, i + 1)) })
      i = Math.max(j, i + 1)
    }
  }
  return tokens
}

const TOKEN_CLASS: Record<string, string> = {
  key: 'text-zinc-300',
  string: 'text-emerald-400',
  number: 'text-amber-400',
  boolean: 'text-amber-300',
  null: 'text-rose-400',
  punct: 'text-muted-foreground',
  ws: '',
}

function JsonViewer({ value, maxH = 'max-h-52' }: { value: unknown; maxH?: string }) {
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(value, null, 2)
  const tokens = useMemo(() => tokenizeJson(json), [json])

  const copy = useCallback(() => {
    void navigator.clipboard.writeText(json)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [json])

  return (
    <div className="relative group">
      <pre className={`rounded-md border border-border bg-muted/30 p-3 text-xs font-mono overflow-auto leading-5 ${maxH}`}>
        {tokens.map((t, i) => (
          <span key={i} className={TOKEN_CLASS[t.type] ?? ''}>
            {t.value}
          </span>
        ))}
      </pre>
      <button
        type="button"
        onClick={copy}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1 rounded-md bg-background border border-border text-muted-foreground hover:text-foreground transition-all"
        title="Copy"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

// ── Status helpers ─────────────────────────────────────────────────────────────

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

// ── Tool filter ────────────────────────────────────────────────────────────────

function ToolFilter({ tools, selected, onChange }: {
  tools: string[]
  selected: string[]
  onChange: (t: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  if (tools.length === 0) return null
  return (
    <div className="relative">
      <Button
        variant={selected.length > 0 ? 'secondary' : 'outline'}
        size="sm"
        className="h-8 text-xs"
        onClick={() => setOpen(p => !p)}
      >
        <Wrench className="h-3 w-3 mr-1" />
        Tools
        {selected.length > 0 && (
          <span className="ml-1 rounded-full bg-primary/20 px-1.5 text-[10px]">{selected.length}</span>
        )}
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-52 rounded-lg border border-border bg-background shadow-xl">
            <div className="p-1 max-h-52 overflow-y-auto">
              {tools.map(tool => (
                <label key={tool} className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-xs hover:bg-accent">
                  <input
                    type="checkbox"
                    checked={selected.includes(tool)}
                    onChange={() =>
                      onChange(selected.includes(tool) ? selected.filter(t => t !== tool) : [...selected, tool])
                    }
                    className="accent-primary"
                  />
                  <span className="truncate font-mono">{tool}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── Evaluation form ────────────────────────────────────────────────────────────

function EvalForm({ agentId, actionId }: { agentId: string; actionId: string }) {
  const [thumbs, setThumbs] = useState<'up' | 'down' | null>(null)
  const [score, setScore] = useState(3)
  const [notes, setNotes] = useState('')
  const [submitted, setSubmitted] = useState<{ rating_thumbs?: string; rating_score?: number; notes?: string } | null>(null)

  const evalMut = useMutation({
    mutationFn: () =>
      submitEvaluation(agentId, actionId, {
        rating_thumbs: thumbs ?? undefined,
        rating_score: score,
        notes: notes.trim() || undefined,
      }),
    onSuccess: (ev) => {
      toast.success('Evaluation submitted')
      setSubmitted({ rating_thumbs: ev.rating_thumbs, rating_score: ev.rating_score, notes: ev.notes ?? undefined })
    },
    onError: () => toast.error('Evaluation failed'),
  })

  if (submitted) {
    return (
      <div className="rounded-lg border border-border bg-card p-3 space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Evaluation submitted</p>
        <div className="flex items-center gap-3">
          {submitted.rating_thumbs && (
            <span className={submitted.rating_thumbs === 'up' ? 'text-emerald-400' : 'text-red-400'}>
              {submitted.rating_thumbs === 'up' ? <ThumbsUp className="h-4 w-4" /> : <ThumbsDown className="h-4 w-4" />}
            </span>
          )}
          {submitted.rating_score !== undefined && (
            <span className="text-sm font-mono font-bold">{submitted.rating_score}/5</span>
          )}
          {submitted.notes && <p className="text-xs text-muted-foreground truncate">{submitted.notes}</p>}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setThumbs(thumbs === 'up' ? null : 'up')}
          className={`p-2 rounded-lg border transition-colors ${thumbs === 'up' ? 'border-emerald-400 bg-emerald-950/40 text-emerald-400' : 'border-border text-muted-foreground hover:text-foreground'}`}
        >
          <ThumbsUp className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setThumbs(thumbs === 'down' ? null : 'down')}
          className={`p-2 rounded-lg border transition-colors ${thumbs === 'down' ? 'border-red-400 bg-red-950/40 text-red-400' : 'border-border text-muted-foreground hover:text-foreground'}`}
        >
          <ThumbsDown className="h-4 w-4" />
        </button>
        <div className="flex-1 flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Score:</span>
          <input
            type="range"
            min="1"
            max="5"
            step="1"
            value={score}
            onChange={e => setScore(Number(e.target.value))}
            className="flex-1 accent-primary cursor-pointer"
          />
          <span className="text-xs font-bold font-mono w-4">{score}</span>
        </div>
      </div>
      <Textarea
        placeholder="Optional notes…"
        value={notes}
        onChange={e => setNotes(e.target.value)}
        rows={2}
        className="text-xs"
      />
      <Button
        size="sm"
        onClick={() => evalMut.mutate()}
        disabled={evalMut.isPending || (!thumbs && !notes.trim())}
        className="w-full"
      >
        {evalMut.isPending ? 'Submitting…' : 'Submit Evaluation'}
      </Button>
    </div>
  )
}

// ── Replay SSE hook ────────────────────────────────────────────────────────────

function useReplaySSE(
  agentId: string,
  replayId: string | null,
  onAction: (a: Action) => void,
  onComplete: () => void,
  onError: () => void,
) {
  const cbAction = useRef(onAction)
  const cbComplete = useRef(onComplete)
  const cbError = useRef(onError)
  cbAction.current = onAction
  cbComplete.current = onComplete
  cbError.current = onError

  useEffect(() => {
    if (!replayId) return
    const creds = getStoredCredentials()
    if (!creds) return

    const ctrl = new AbortController()

    async function go() {
      try {
        const res = await fetch(
          `${creds!.baseURL}/v1/agents/${agentId}/replays/${replayId}/stream`,
          { headers: { 'X-API-Key': creds!.apiKey }, signal: ctrl.signal },
        )
        if (!res.ok || !res.body) { cbError.current(); return }

        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        let evt = ''

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
                const data = JSON.parse(line.slice(6)) as unknown
                if (evt === 'action') cbAction.current(data as Action)
                else if (evt === 'completed') cbComplete.current()
              } catch {}
              evt = ''
            }
          }
        }
        cbComplete.current()
      } catch (e) {
        if (e instanceof Error && e.name === 'AbortError') return
        cbError.current()
      }
    }

    void go()
    return () => ctrl.abort()
  }, [agentId, replayId])
}

// ── Replay Modal ──────────────────────────────────────────────────────────────

const SPEEDS = [1, 2, 5, 10] as const
type ReplayPhase = 'setup' | 'running' | 'done' | 'error'

function ReplayModal({
  agentId,
  initialFrom,
  open,
  onClose,
}: {
  agentId: string
  initialFrom?: string
  open: boolean
  onClose: () => void
}) {
  const toLocal = (iso?: string) => {
    if (!iso) return format(new Date(), "yyyy-MM-dd'T'HH:mm")
    const d = new Date(iso)
    return format(d, "yyyy-MM-dd'T'HH:mm")
  }

  const [fromTs, setFromTs] = useState(() => toLocal(initialFrom))
  const [toTs, setToTs] = useState(() => toLocal())
  const [speed, setSpeed] = useState<number>(1)
  const [phase, setPhase] = useState<ReplayPhase>('setup')
  const [replay, setReplay] = useState<Replay | null>(null)
  const [replayId, setReplayId] = useState<string | null>(null)
  const [receivedActions, setReceivedActions] = useState<Action[]>([])
  const [displayCount, setDisplayCount] = useState(0)
  const [paused, setPaused] = useState(false)
  const pausedRef = useRef(false)
  pausedRef.current = paused

  // Reset when initialFrom changes (new "start from here" click)
  useEffect(() => {
    if (open) {
      setFromTs(toLocal(initialFrom))
      setToTs(toLocal())
      setPhase('setup')
      setReplay(null)
      setReplayId(null)
      setReceivedActions([])
      setDisplayCount(0)
      setPaused(false)
    }
  }, [open, initialFrom])

  const createMut = useMutation({
    mutationFn: () =>
      createReplay(agentId, new Date(fromTs).toISOString(), new Date(toTs).toISOString(), speed),
    onSuccess: (r) => {
      setReplay(r)
      setReplayId(r.id)
      setPhase('running')
    },
    onError: () => toast.error('Failed to create replay'),
  })

  const handleAction = useCallback((a: Action) => {
    setReceivedActions(prev => [...prev, a])
    if (!pausedRef.current) setDisplayCount(prev => prev + 1)
  }, [])

  const handleComplete = useCallback(() => {
    setDisplayCount(prev => {
      setReceivedActions(all => { setDisplayCount(all.length); return all })
      return prev
    })
    setPhase('done')
  }, [])

  const handleError = useCallback(() => setPhase('error'), [])

  useReplaySSE(agentId, replayId, handleAction, handleComplete, handleError)

  const displayedActions = receivedActions.slice(0, displayCount)
  const currentAction = displayedActions.at(-1)
  const total = replay?.action_count ?? 0

  const handleResume = () => {
    setPaused(false)
    setDisplayCount(receivedActions.length)
  }

  const handleStop = () => {
    setReplayId(null)
    setPhase('done')
    setDisplayCount(receivedActions.length)
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Replay"
      description={replay ? `Replaying ${replay.action_count} actions at ${replay.speed}×` : 'Configure and start a replay'}
    >
      {phase === 'setup' && (
        <div className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">From</label>
            <Input
              type="datetime-local"
              value={fromTs}
              onChange={e => setFromTs(e.target.value)}
              className="text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">To</label>
            <Input
              type="datetime-local"
              value={toTs}
              onChange={e => setToTs(e.target.value)}
              className="text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Speed</label>
            <div className="flex gap-2">
              {SPEEDS.map(s => (
                <Button
                  key={s}
                  variant={speed === s ? 'secondary' : 'outline'}
                  size="sm"
                  onClick={() => setSpeed(s)}
                  className="flex-1 text-xs"
                >
                  {s}×
                </Button>
              ))}
            </div>
          </div>
          <Button
            className="w-full"
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending || !fromTs || !toTs}
          >
            <Play className="h-4 w-4 mr-2" />
            {createMut.isPending ? 'Creating…' : 'Start Replay'}
          </Button>
        </div>
      )}

      {(phase === 'running' || phase === 'done') && (
        <div className="space-y-4">
          {/* Progress */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {phase === 'done' ? 'Completed' : paused ? 'Paused' : 'Running…'}
                {total > 0 && ` — ${displayCount} / ${total}`}
              </span>
              {phase === 'running' && (
                <span className="text-xs text-muted-foreground">{speed}×</span>
              )}
            </div>
            <div className="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${phase === 'done' ? 'bg-emerald-400' : 'bg-primary'}`}
                style={{ width: total > 0 ? `${(displayCount / total) * 100}%` : '0%' }}
              />
            </div>
          </div>

          {/* Controls */}
          {phase === 'running' && (
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={paused ? handleResume : () => setPaused(true)}
              >
                {paused ? <Play className="h-3.5 w-3.5 mr-1" /> : <Pause className="h-3.5 w-3.5 mr-1" />}
                {paused ? 'Resume' : 'Pause'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-destructive hover:text-destructive"
                onClick={handleStop}
              >
                <Square className="h-3.5 w-3.5 mr-1" />
                Stop
              </Button>
            </div>
          )}

          {/* Timeline */}
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {displayedActions.length === 0 ? (
              <div className="text-center py-4 text-xs text-muted-foreground">
                {phase === 'running' ? 'Waiting for first action…' : 'No actions in this range'}
              </div>
            ) : (
              [...displayedActions].reverse().map((a, i) => {
                const isCurrent = i === 0 && phase === 'running'
                return (
                  <div
                    key={a.id}
                    className={`flex items-center gap-2 rounded-md p-2 text-xs transition-all ${
                      isCurrent ? 'bg-primary/10 border border-primary/40 animate-pulse' : 'bg-muted/30'
                    }`}
                  >
                    <div className={`h-2 w-2 rounded-full shrink-0 ${STATUS_BG[a.status]}`} />
                    <span className="font-mono font-medium truncate flex-1">{a.tool_name}</span>
                    <Badge variant={STATUS_VARIANT[a.status]} className="text-[10px] shrink-0">
                      {a.status}
                    </Badge>
                    {a.duration_ms != null && (
                      <span className="text-muted-foreground shrink-0">
                        {formatDuration(a.duration_ms)}
                      </span>
                    )}
                  </div>
                )
              })
            )}
          </div>

          {/* Current action input/output */}
          {currentAction && (
            <div className="space-y-2 border-t border-border pt-3">
              <p className="text-xs font-medium text-muted-foreground">
                {phase === 'running' ? 'Current action' : 'Last action'}: {currentAction.tool_name}
              </p>
              <div className="space-y-1">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Input</p>
                <JsonViewer value={currentAction.input_params} maxH="max-h-24" />
              </div>
              <div className="space-y-1">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Output</p>
                <JsonViewer value={currentAction.output_result} maxH="max-h-24" />
              </div>
            </div>
          )}

          {phase === 'done' && (
            <Button variant="outline" className="w-full" onClick={() => setPhase('setup')}>
              Start New Replay
            </Button>
          )}
        </div>
      )}

      {phase === 'error' && (
        <div className="space-y-4">
          <p className="text-sm text-destructive">Replay stream failed. Try again.</p>
          <Button variant="outline" className="w-full" onClick={() => setPhase('setup')}>
            Back to Setup
          </Button>
        </div>
      )}
    </Sheet>
  )
}

// ── Action Detail Drawer ──────────────────────────────────────────────────────

function ActionDetailDrawer({
  agentId,
  action,
  onClose,
  onReplay,
}: {
  agentId: string
  action: Action | null
  onClose: () => void
  onReplay: (action: Action) => void
}) {
  return (
    <Sheet
      open={!!action}
      onClose={onClose}
      title={action?.tool_name ?? ''}
      description={action ? `${formatDateTime(action.timestamp)}${action.duration_ms != null ? ` · ${formatDuration(action.duration_ms)}` : ''}` : undefined}
    >
      {action && (
        <div className="space-y-5">
          {/* Header badges */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={STATUS_VARIANT[action.status]} className="capitalize">
              {action.status}
            </Badge>
            {action.duration_ms != null && (
              <Badge variant="secondary" className="text-xs font-mono">
                {formatDuration(action.duration_ms)}
              </Badge>
            )}
            {action.session_id && (
              <Badge variant="secondary" className="text-xs font-mono">
                session: {action.session_id.slice(0, 8)}…
              </Badge>
            )}
            {action.metadata?.prompt_version_id && (
              <Badge variant="info" className="text-xs">
                prompt v{String(action.metadata.prompt_version_id).slice(0, 8)}…
              </Badge>
            )}
          </div>

          {/* Input */}
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Input</p>
            <JsonViewer value={action.input_params} maxH="max-h-48" />
          </div>

          {/* Output / Error */}
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {action.status === 'error' && action.error_msg ? 'Error' : 'Output'}
            </p>
            {action.status === 'error' && action.error_msg ? (
              <div className="rounded-md border border-red-800/50 bg-red-950/30 p-3 text-xs font-mono text-red-300 max-h-48 overflow-auto">
                {action.error_msg}
              </div>
            ) : (
              <JsonViewer value={action.output_result} maxH="max-h-48" />
            )}
          </div>

          {/* Evaluation */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Evaluation
            </p>
            <EvalForm agentId={agentId} actionId={action.id} />
          </div>

          {/* Replay */}
          <Button
            variant="outline"
            className="w-full gap-2"
            onClick={() => onReplay(action)}
          >
            <Play className="h-4 w-4" />
            Start Replay from here
          </Button>
        </div>
      )}
    </Sheet>
  )
}

// ── Stats bar ─────────────────────────────────────────────────────────────────

const CHART = {
  grid: 'hsl(217.2 32.6% 17.5%)',
  tick: { fontSize: 10, fill: 'hsl(215 20.2% 55%)' },
  tooltip: {
    contentStyle: {
      backgroundColor: 'hsl(222.2 84% 5%)',
      border: '1px solid hsl(217.2 32.6% 17.5%)',
      borderRadius: 6,
      fontSize: 11,
    },
  },
} as const

function ActionStatsBar({ agentId }: { agentId: string }) {
  const since7d = useMemo(() => subDays(new Date(), 7).toISOString(), [])

  const { data: stats } = useQuery({
    queryKey: ['action-stats', agentId],
    queryFn: () => getActionStats(agentId),
    staleTime: 60_000,
    retry: false,
  })

  const { data: recent7d } = useQuery({
    queryKey: ['actions-7d', agentId],
    queryFn: () => listActions(agentId, { since: since7d, limit: 100 }),
    staleTime: 60_000,
    retry: false,
  })

  const chartData = useMemo(() => {
    const days = Array.from({ length: 7 }, (_, i) => ({
      day: format(subDays(new Date(), 6 - i), 'M/d'),
      success: 0,
      error: 0,
      timeout: 0,
    }))
    recent7d?.items.forEach(a => {
      const diff = differenceInDays(new Date(), new Date(a.timestamp))
      if (diff >= 0 && diff < 7) {
        const s = a.status as string
        const bucket = days[6 - diff] as Record<string, number>
        if (s in bucket) bucket[s]++
      }
    })
    return days
  }, [recent7d])

  const topTool = stats?.by_tool[0]?.tool_name

  if (!stats) return null

  const successRate = (1 - stats.error_rate) * 100

  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Activity className="h-3.5 w-3.5 text-zinc-300" />
            <span className="text-xs text-muted-foreground">Total</span>
          </div>
          <div className="text-xl font-bold">{formatNumber(stats.total_actions)}</div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Zap className="h-3.5 w-3.5 text-emerald-400" />
            <span className="text-xs text-muted-foreground">Success rate</span>
          </div>
          <div className="text-xl font-bold">{successRate.toFixed(1)}%</div>
          <div className="mt-1.5 h-1 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full ${successRate >= 90 ? 'bg-emerald-400' : successRate >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${successRate}%` }}
            />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Avg latency</span>
          </div>
          <div className="text-xl font-bold">
            {stats.avg_duration_ms != null ? formatDuration(stats.avg_duration_ms) : '—'}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Top tool</span>
          </div>
          <div className="text-sm font-bold font-mono truncate">{topTool ?? '—'}</div>
        </CardContent>
      </Card>

      {/* 7-day chart spans full width */}
      <Card className="col-span-2 lg:col-span-4">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-medium text-muted-foreground">Actions last 7 days</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={chartData} barSize={8}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
              <XAxis dataKey="day" tick={CHART.tick} tickLine={false} axisLine={false} />
              <Tooltip {...CHART.tooltip} />
              <Bar dataKey="success" stackId="a" fill="hsl(142 71% 45%)" radius={[0,0,0,0]} />
              <Bar dataKey="error" stackId="a" fill="hsl(0 62.8% 50%)" radius={[0,0,0,0]} />
              <Bar dataKey="timeout" stackId="a" fill="hsl(43 96% 56%)" radius={[2,2,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Main ActionsTab ───────────────────────────────────────────────────────────

export function ActionsTab({ agentId }: { agentId: string }) {
  // Filters
  const [toolFilter, setToolFilter] = useState<string[]>([])
  const [statusFilter, setStatusFilter] = useState<ActionStatus | ''>('')
  const [sinceDate, setSinceDate] = useState('')
  const [untilDate, setUntilDate] = useState('')
  const [searchText, setSearchText] = useState('')

  // Pagination
  const [extraActions, setExtraActions] = useState<Action[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  // Detail / replay
  const [selectedAction, setSelectedAction] = useState<Action | null>(null)
  const [replayOpen, setReplayOpen] = useState(false)
  const [replayFromAction, setReplayFromAction] = useState<Action | null>(null)

  // Initial query
  const { data: page1, isLoading, refetch } = useQuery({
    queryKey: ['actions-tab', agentId, statusFilter, sinceDate, untilDate],
    queryFn: () =>
      listActions(agentId, {
        status: statusFilter || undefined,
        since: sinceDate ? new Date(sinceDate).toISOString() : undefined,
        until: untilDate ? new Date(untilDate).toISOString() : undefined,
        limit: 50,
      }),
    staleTime: 30_000,
    retry: false,
  })

  // Reset extras when filters change (page1 first item changes)
  useEffect(() => {
    setExtraActions([])
    setNextCursor(page1?.next_cursor ?? null)
  }, [page1?.items[0]?.id])

  const allLoaded = [...(page1?.items ?? []), ...extraActions]

  // All unique tools for filter
  const allTools = useMemo(() => {
    const s = new Set<string>()
    allLoaded.forEach(a => s.add(a.tool_name))
    return [...s].sort()
  }, [allLoaded])

  // Max duration for proportional bars
  const maxDuration = useMemo(
    () => Math.max(...allLoaded.map(a => a.duration_ms ?? 0), 1),
    [allLoaded],
  )

  // Client-side filter by tool + text search
  const filtered = useMemo(() => {
    let list = allLoaded
    if (toolFilter.length > 0) list = list.filter(a => toolFilter.includes(a.tool_name))
    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter(
        a =>
          JSON.stringify(a.input_params).toLowerCase().includes(q) ||
          JSON.stringify(a.output_result).toLowerCase().includes(q),
      )
    }
    return list
  }, [allLoaded, toolFilter, searchText])

  const hasFilters = toolFilter.length > 0 || !!statusFilter || !!sinceDate || !!untilDate || !!searchText

  const clearFilters = () => {
    setToolFilter([])
    setStatusFilter('')
    setSinceDate('')
    setUntilDate('')
    setSearchText('')
  }

  async function loadMore() {
    if (!nextCursor) return
    setLoadingMore(true)
    try {
      const res = await listActions(agentId, {
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

  const handleReplayFromAction = (action: Action) => {
    setReplayFromAction(action)
    setSelectedAction(null)
    setReplayOpen(true)
  }

  return (
    <div className="space-y-4 pt-4">
      {/* Stats */}
      <ActionStatsBar agentId={agentId} />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-48">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search params…"
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            className="pl-8 h-8 text-xs"
          />
        </div>

        <ToolFilter tools={allTools} selected={toolFilter} onChange={setToolFilter} />

        {/* Status filter */}
        <div className="flex gap-1">
          {(['', 'success', 'error', 'timeout'] as const).map(s => (
            <Button
              key={s}
              variant={statusFilter === s ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 text-xs"
              onClick={() => setStatusFilter(s)}
            >
              {s === '' ? 'All' : s}
            </Button>
          ))}
        </div>

        {/* Date range */}
        <div className="flex items-center gap-1">
          <Input
            type="date"
            value={sinceDate}
            onChange={e => setSinceDate(e.target.value)}
            className="h-8 text-xs w-32"
            title="Since"
          />
          <span className="text-xs text-muted-foreground">–</span>
          <Input
            type="date"
            value={untilDate}
            onChange={e => setUntilDate(e.target.value)}
            className="h-8 text-xs w-32"
            title="Until"
          />
        </div>

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

      {/* Table */}
      {isLoading ? (
        <div className="space-y-1.5">
          {[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-12 rounded-md" />)}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Activity}
          title={hasFilters ? 'No actions match your filters' : 'No actions yet'}
          description={hasFilters ? 'Try adjusting or clearing the filters.' : 'Actions will appear here as the agent uses tools.'}
          action={hasFilters ? <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button> : undefined}
        />
      ) : (
        <>
          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Timestamp
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Tool
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Status
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide w-40">
                    Duration
                  </th>
                  <th className="px-3 py-2 w-8" />
                </tr>
              </thead>
              <tbody>
                {filtered.map(action => (
                  <tr
                    key={action.id}
                    className="border-b border-border/50 hover:bg-accent/30 cursor-pointer transition-colors group"
                    onClick={() => setSelectedAction(action)}
                  >
                    <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                      {formatDateTime(action.timestamp)}
                    </td>
                    <td className="px-3 py-2.5">
                      <code className="text-xs font-semibold">{action.tool_name}</code>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge variant={STATUS_VARIANT[action.status]} className="text-xs capitalize">
                        {action.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5">
                      {action.duration_ms != null ? (
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
                            <div
                              className={`h-full rounded-full ${STATUS_BG[action.status]}`}
                              style={{ width: `${(action.duration_ms / maxDuration) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono text-muted-foreground shrink-0 w-12 text-right">
                            {formatDuration(action.duration_ms)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Load more */}
          {nextCursor && (
            <div className="flex justify-center pt-1">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void loadMore()}
                disabled={loadingMore}
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}

      {/* Detail drawer */}
      <ActionDetailDrawer
        agentId={agentId}
        action={selectedAction}
        onClose={() => setSelectedAction(null)}
        onReplay={handleReplayFromAction}
      />

      {/* Replay modal */}
      <ReplayModal
        agentId={agentId}
        initialFrom={replayFromAction?.timestamp}
        open={replayOpen}
        onClose={() => {
          setReplayOpen(false)
          setReplayFromAction(null)
        }}
      />
    </div>
  )
}
