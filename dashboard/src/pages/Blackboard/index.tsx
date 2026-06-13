import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Share2,
  Trash2,
  Plus,
  RefreshCw,
  Clock,
  History,
  RotateCcw,
  Save,
  ChevronRight,
  X,
  Wifi,
} from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'
import { toast } from 'sonner'

import {
  listNamespaceKeys,
  writeContext,
  deleteContext,
  getContextHistory,
  rollbackContext,
} from '@/api/context'
import { getStoredCredentials } from '@/hooks/useApiKey'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import type { ContextEntry, ContextHistoryEntry } from '@/types/api'

// ── Diff utility ─────────────────────────────────────────────────────────────

interface DiffLine {
  type: '=' | '+' | '-'
  line: string
}

function lcsMatrix(a: string[], b: string[]): number[][] {
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }
  return dp
}

function diffLines(prev: string, curr: string): DiffLine[] {
  const a = prev.split('\n')
  const b = curr.split('\n')
  const dp = lcsMatrix(a, b)
  const result: DiffLine[] = []
  let i = a.length
  let j = b.length
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      result.unshift({ type: '=', line: a[i - 1] })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ type: '+', line: b[j - 1] })
      j--
    } else {
      result.unshift({ type: '-', line: a[i - 1] })
      i--
    }
  }
  return result
}

// ── SSE hook ─────────────────────────────────────────────────────────────────

interface SSEEvent {
  event: string
  key?: string
  version?: number
}

function useNamespaceSSE(
  namespace: string,
  enabled: boolean,
  onEvent: (ev: SSEEvent) => void,
) {
  const cbRef = useRef(onEvent)
  cbRef.current = onEvent

  useEffect(() => {
    if (!enabled || !namespace) return
    const creds = getStoredCredentials()
    if (!creds) return

    const ctrl = new AbortController()
    let stopped = false

    async function connect() {
      try {
        const res = await fetch(
          `${creds!.baseURL}/v1/context/${encodeURIComponent(namespace)}/subscribe`,
          {
            headers: { 'X-API-Key': creds!.apiKey },
            signal: ctrl.signal,
          },
        )
        if (!res.ok || !res.body) return

        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        let evtType = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''
          for (const line of lines) {
            if (line.startsWith('event: ')) evtType = line.slice(7).trim()
            else if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6)) as Record<string, unknown>
                cbRef.current({ event: evtType, ...data } as SSEEvent)
              } catch {}
              evtType = ''
            }
          }
        }
      } catch (e) {
        if (stopped) return
        if (e instanceof Error && e.name === 'AbortError') return
        setTimeout(() => {
          if (!stopped) void connect()
        }, 3000)
      }
    }

    void connect()
    return () => {
      stopped = true
      ctrl.abort()
    }
  }, [namespace, enabled])
}

// ── Diff view ─────────────────────────────────────────────────────────────────

function DiffView({ prev, curr }: { prev: string; curr: string }) {
  const lines = diffLines(prev, curr)
  return (
    <div className="rounded-md border border-border bg-muted/30 overflow-auto max-h-72 text-xs font-mono">
      {lines.map((l, i) => (
        <div
          key={i}
          className={
            l.type === '+'
              ? 'bg-emerald-950/60 text-emerald-300 px-3 py-0.5'
              : l.type === '-'
              ? 'bg-red-950/60 text-red-300 px-3 py-0.5'
              : 'px-3 py-0.5 text-muted-foreground'
          }
        >
          <span className="select-none mr-2 opacity-50">
            {l.type === '+' ? '+' : l.type === '-' ? '-' : ' '}
          </span>
          {l.line}
        </div>
      ))}
    </div>
  )
}

// ── Key detail panel ──────────────────────────────────────────────────────────

function KeyPanel({
  namespace,
  entry,
  onClose,
  onDeleted,
}: {
  namespace: string
  entry: ContextEntry
  onClose: () => void
  onDeleted: () => void
}) {
  const qc = useQueryClient()
  const [editorValue, setEditorValue] = useState(JSON.stringify(entry.value, null, 2))
  const [jsonError, setJsonError] = useState('')
  const [writtenBy, setWrittenBy] = useState('')
  const [historyPanel, setHistoryPanel] = useState(false)
  const [diffTarget, setDiffTarget] = useState<ContextHistoryEntry | null>(null)

  // Keep editor in sync if the entry changes (e.g., after SSE update)
  useEffect(() => {
    setEditorValue(JSON.stringify(entry.value, null, 2))
    setDiffTarget(null)
  }, [entry.id, entry.version])

  const { data: history, isLoading: histLoading } = useQuery({
    queryKey: ['context-history', namespace, entry.key],
    queryFn: () => getContextHistory(namespace, entry.key),
    enabled: historyPanel,
    staleTime: 30_000,
  })

  const saveMut = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(editorValue) as Record<string, unknown>
        if (typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
      } catch {
        throw new Error('JSON_PARSE')
      }
      return writeContext(namespace, entry.key, parsed, {
        written_by: writtenBy.trim() || undefined,
        expected_version: entry.version,
      })
    },
    onSuccess: () => {
      toast.success('Saved')
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      void qc.invalidateQueries({ queryKey: ['context-history', namespace, entry.key] })
      setJsonError('')
    },
    onError: (err) => {
      if ((err as Error).message === 'JSON_PARSE') {
        setJsonError('Must be a valid JSON object {}')
      } else {
        toast.error('Save failed')
      }
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteContext(namespace, entry.key),
    onSuccess: () => {
      toast.success(`Key "${entry.key}" deleted`)
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      onDeleted()
    },
    onError: () => toast.error('Delete failed'),
  })

  const rollbackMut = useMutation({
    mutationFn: (v: number) => rollbackContext(namespace, entry.key, v),
    onSuccess: (result) => {
      toast.success(`Rolled back to v${result.restored_version} (new: v${result.new_version})`)
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      void qc.invalidateQueries({ queryKey: ['context-history', namespace, entry.key] })
      setDiffTarget(null)
    },
    onError: () => toast.error('Rollback failed'),
  })

  const currentJson = JSON.stringify(entry.value, null, 2)

  return (
    <div className="flex flex-col h-full border-l border-border">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <code className="text-sm font-semibold truncate">{entry.key}</code>
          <Badge variant="secondary" className="text-xs shrink-0">v{entry.version}</Badge>
          {entry.expires_at && (
            <Badge variant="warning" className="text-xs shrink-0">
              expires {formatDistanceToNow(new Date(entry.expires_at), { addSuffix: true })}
            </Badge>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* JSON editor */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Value (JSON object)
          </label>
          <Textarea
            value={editorValue}
            onChange={(e) => {
              setEditorValue(e.target.value)
              setJsonError('')
            }}
            rows={8}
            className={`font-mono text-xs ${jsonError ? 'border-destructive' : ''}`}
          />
          {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
        </div>

        {/* written_by */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Written by (optional)
          </label>
          <Input
            placeholder="agent UUID or name"
            value={writtenBy}
            onChange={(e) => setWrittenBy(e.target.value)}
            className="text-xs h-8"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button
            size="sm"
            className="flex-1"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
          >
            <Save className="h-3.5 w-3.5" />
            {saveMut.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className={`text-xs ${historyPanel ? 'bg-accent' : ''}`}
            onClick={() => setHistoryPanel((p) => !p)}
          >
            <History className="h-3.5 w-3.5" />
            History
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => {
              if (confirm(`Delete key "${entry.key}"?`)) deleteMut.mutate()
            }}
            disabled={deleteMut.isPending}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Metadata */}
        <p className="text-xs text-muted-foreground">
          Updated {formatDistanceToNow(new Date(entry.updated_at), { addSuffix: true })}
          {entry.written_by && ` by ${entry.written_by}`}
        </p>

        {/* History panel */}
        {historyPanel && (
          <div className="space-y-3">
            <div className="border-t border-border pt-3">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                Version History
              </h4>
              {histLoading ? (
                <div className="space-y-1.5">
                  {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-md" />)}
                </div>
              ) : !history || history.entries.length === 0 ? (
                <p className="text-xs text-muted-foreground">No history available</p>
              ) : (
                <div className="space-y-1.5">
                  {history.entries.map((h) => {
                    const isSelected = diffTarget?.id === h.id
                    return (
                      <div
                        key={h.id}
                        className={`rounded-md border border-border p-2.5 space-y-1 ${
                          isSelected ? 'border-primary bg-primary/5' : 'bg-muted/20'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-semibold">
                              v{h.version}
                            </span>
                            <Badge variant="secondary" className="text-[10px]">
                              {h.operation}
                            </Badge>
                            {h.written_by && (
                              <span className="text-[10px] text-muted-foreground truncate max-w-[100px]">
                                by {h.written_by}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              type="button"
                              onClick={() => setDiffTarget(isSelected ? null : h)}
                              className="text-[10px] text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-accent transition-colors"
                            >
                              {isSelected ? 'Hide diff' : 'Diff'}
                            </button>
                            {h.value !== null && h.version !== entry.version && (
                              <button
                                type="button"
                                onClick={() => rollbackMut.mutate(h.version)}
                                disabled={rollbackMut.isPending}
                                className="text-[10px] text-amber-400 hover:text-amber-300 px-1.5 py-0.5 rounded hover:bg-amber-950/30 transition-colors flex items-center gap-0.5"
                              >
                                <RotateCcw className="h-2.5 w-2.5" />
                                Restore
                              </button>
                            )}
                          </div>
                        </div>
                        <p className="text-[10px] text-muted-foreground">
                          {format(new Date(h.timestamp), 'MMM d, yyyy HH:mm:ss')}
                        </p>

                        {isSelected && h.value !== null && (
                          <DiffView
                            prev={JSON.stringify(h.value, null, 2)}
                            curr={currentJson}
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Key list item ─────────────────────────────────────────────────────────────

function KeyItem({
  entry,
  selected,
  onClick,
  flash,
}: {
  entry: ContextEntry
  selected: boolean
  onClick: () => void
  flash: boolean
}) {
  const preview = (() => {
    try {
      const s = JSON.stringify(entry.value)
      return s.length > 60 ? s.slice(0, 57) + '…' : s
    } catch {
      return String(entry.value)
    }
  })()

  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-md transition-colors border ${
        selected
          ? 'border-primary/60 bg-primary/5'
          : 'border-transparent hover:bg-accent/50'
      } ${flash ? 'ring-1 ring-emerald-400' : ''}`}
    >
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <code className="text-xs font-semibold truncate">{entry.key}</code>
        <span className="text-[10px] text-muted-foreground shrink-0">v{entry.version}</span>
      </div>
      <p className="text-[11px] text-muted-foreground truncate font-mono">{preview}</p>
      <p className="text-[10px] text-muted-foreground/60 mt-0.5 flex items-center gap-1">
        <Clock className="h-2.5 w-2.5" />
        {formatDistanceToNow(new Date(entry.updated_at), { addSuffix: true })}
        {entry.written_by && ` · ${entry.written_by}`}
      </p>
    </button>
  )
}

// ── New Key form ──────────────────────────────────────────────────────────────

function NewKeyForm({
  namespace,
  onDone,
}: {
  namespace: string
  onDone: () => void
}) {
  const qc = useQueryClient()
  const [key, setKey] = useState('')
  const [valueText, setValueText] = useState('{}')
  const [jsonError, setJsonError] = useState('')

  const createMut = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(valueText) as Record<string, unknown>
        if (typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
      } catch {
        throw new Error('JSON_PARSE')
      }
      return writeContext(namespace, key.trim(), parsed)
    },
    onSuccess: () => {
      toast.success(`Key "${key}" created`)
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      onDone()
    },
    onError: (err) => {
      if ((err as Error).message === 'JSON_PARSE') {
        setJsonError('Must be a valid JSON object {}')
      } else {
        toast.error('Failed to create key')
      }
    },
  })

  return (
    <div className="border border-border rounded-lg p-4 space-y-3 bg-card">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">New Key</h4>
        <button
          type="button"
          onClick={onDone}
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <Input
        placeholder="key-name"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="font-mono text-sm"
        autoFocus
      />
      <div className="space-y-1">
        <Textarea
          placeholder='{"value": "here"}'
          value={valueText}
          onChange={(e) => {
            setValueText(e.target.value)
            setJsonError('')
          }}
          rows={3}
          className={`font-mono text-xs ${jsonError ? 'border-destructive' : ''}`}
        />
        {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          className="flex-1"
          onClick={() => createMut.mutate()}
          disabled={!key.trim() || createMut.isPending}
        >
          {createMut.isPending ? 'Creating…' : 'Create'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BlackboardPage() {
  const qc = useQueryClient()
  const [nsInput, setNsInput] = useState('default')
  const [namespace, setNamespace] = useState('default')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [showNewKey, setShowNewKey] = useState(false)
  const [sseEnabled, setSseEnabled] = useState(true)
  const [liveFlash, setLiveFlash] = useState(false)
  const [flashedKeys, setFlashedKeys] = useState<Set<string>>(new Set())

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['context', namespace],
    queryFn: () => listNamespaceKeys(namespace),
    staleTime: 30_000,
  })

  const selectedEntry = data?.entries.find((e) => e.key === selectedKey) ?? null

  const handleSSEEvent = useCallback(
    (ev: SSEEvent) => {
      if (ev.event === 'heartbeat') return
      setLiveFlash(true)
      setTimeout(() => setLiveFlash(false), 1500)

      if (ev.key) {
        setFlashedKeys((prev) => new Set(prev).add(ev.key!))
        setTimeout(
          () =>
            setFlashedKeys((prev) => {
              const next = new Set(prev)
              next.delete(ev.key!)
              return next
            }),
          2000,
        )
        void qc.invalidateQueries({ queryKey: ['context', namespace] })
      }
    },
    [namespace, qc],
  )

  useNamespaceSSE(namespace, sseEnabled, handleSSEEvent)

  return (
    <div className="flex flex-col h-full">
      {/* ── Top bar ── */}
      <div className="flex items-center gap-2 px-6 py-4 border-b border-border shrink-0 flex-wrap">
        <h1 className="text-lg font-semibold tracking-tight mr-2">Blackboard</h1>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            setNamespace(nsInput)
            setSelectedKey(null)
            setShowNewKey(false)
          }}
          className="flex items-center gap-2"
        >
          <Input
            placeholder="Namespace"
            value={nsInput}
            onChange={(e) => setNsInput(e.target.value)}
            className="w-36 h-8 text-sm font-mono"
          />
          <Button type="submit" variant="secondary" size="sm" className="h-8">
            Load
          </Button>
        </form>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => void refetch()}
          title="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>

        {/* SSE indicator */}
        <button
          type="button"
          onClick={() => setSseEnabled((p) => !p)}
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-all ${
            sseEnabled
              ? liveFlash
                ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-400'
                : 'bg-emerald-950/40 text-emerald-500'
              : 'bg-muted text-muted-foreground'
          }`}
          title={sseEnabled ? 'Click to disconnect live updates' : 'Click to enable live updates'}
        >
          <Wifi className={`h-3 w-3 ${sseEnabled && liveFlash ? 'animate-pulse' : ''}`} />
          {sseEnabled ? 'Live' : 'Paused'}
        </button>

        <Button
          variant="outline"
          size="sm"
          className="h-8 ml-auto gap-1"
          onClick={() => {
            setShowNewKey(true)
            setSelectedKey(null)
          }}
        >
          <Plus className="h-4 w-4" />
          New Key
        </Button>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 min-h-0">
        {/* Left: key list */}
        <div className="w-72 shrink-0 flex flex-col border-r border-border">
          <div className="px-3 py-2 border-b border-border">
            <p className="text-xs text-muted-foreground">
              <code className="font-mono">{namespace}</code>
              {data && ` · ${data.count ?? 0} key${(data.count ?? 0) !== 1 ? 's' : ''}`}
            </p>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {isLoading ? (
              <div className="space-y-1.5 p-1">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14 rounded-md" />
                ))}
              </div>
            ) : (data?.entries.length ?? 0) === 0 ? (
              <div className="p-4 text-center">
                <Share2 className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
                <p className="text-xs text-muted-foreground">
                  Namespace "{namespace}" is empty
                </p>
              </div>
            ) : (
              data?.entries.map((entry) => (
                <KeyItem
                  key={entry.id}
                  entry={entry}
                  selected={selectedKey === entry.key}
                  onClick={() => {
                    setSelectedKey(entry.key)
                    setShowNewKey(false)
                  }}
                  flash={flashedKeys.has(entry.key)}
                />
              ))
            )}
          </div>
        </div>

        {/* Right: detail / new key form */}
        <div className="flex-1 min-w-0">
          {showNewKey ? (
            <div className="p-6">
              <NewKeyForm
                namespace={namespace}
                onDone={() => {
                  setShowNewKey(false)
                }}
              />
            </div>
          ) : selectedEntry ? (
            <KeyPanel
              key={selectedEntry.key + selectedEntry.version}
              namespace={namespace}
              entry={selectedEntry}
              onClose={() => setSelectedKey(null)}
              onDeleted={() => setSelectedKey(null)}
            />
          ) : (
            <EmptyState
              icon={ChevronRight}
              title="Select a key"
              description="Click a key on the left to view and edit its value."
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowNewKey(true)}
                >
                  <Plus className="h-4 w-4" />
                  New Key
                </Button>
              }
            />
          )}
        </div>
      </div>
    </div>
  )
}
