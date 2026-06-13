import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search,
  Plus,
  Trash2,
  Brain,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  BookOpen,
  MessageSquare,
  Zap,
  Archive,
  X,
} from 'lucide-react'
import { format } from 'date-fns'
import { toast } from 'sonner'

import {
  listMemories,
  recallMemories,
  deleteMemory,
  getMemoryStats,
  appendMemory,
  getShortMemory,
  extractMemories,
} from '@/api/memory'
import { listEpisodes, getEpisodeDetail } from '@/api/episodes'
import { listSessions } from '@/api/sessions'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import type { Memory, Episode, EpisodeDetail } from '@/types/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function importanceBg(v: number) {
  if (v < 0.3) return 'bg-red-500'
  if (v < 0.7) return 'bg-amber-400'
  return 'bg-emerald-400'
}

function importanceText(v: number) {
  if (v < 0.3) return 'text-red-400'
  if (v < 0.7) return 'text-amber-400'
  return 'text-emerald-400'
}

function fmtDate(s: string) {
  return format(new Date(s), 'MMM d, yyyy HH:mm')
}

// ── Add Memory Dialog ─────────────────────────────────────────────────────────

function AddMemoryDialog({
  agentId,
  open,
  onClose,
}: {
  agentId: string
  open: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [content, setContent] = useState('')
  const [importance, setImportance] = useState(0.5)
  const [tagsInput, setTagsInput] = useState('')

  const addMut = useMutation({
    mutationFn: () => {
      const tags = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
      return appendMemory(agentId, content.trim(), importance, tags)
    },
    onSuccess: () => {
      toast.success('Memory added')
      void qc.invalidateQueries({ queryKey: ['memories', agentId] })
      void qc.invalidateQueries({ queryKey: ['memory-stats', agentId] })
      setContent('')
      setImportance(0.5)
      setTagsInput('')
      onClose()
    },
    onError: () => toast.error('Failed to add memory'),
  })

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Memory</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Content *</label>
            <Textarea
              placeholder="What should the agent remember?"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Importance</label>
              <span className={`text-sm font-mono font-bold ${importanceText(importance)}`}>
                {importance.toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={importance}
              onChange={(e) => setImportance(parseFloat(e.target.value))}
              className="w-full accent-primary cursor-pointer"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Low</span>
              <span>Medium</span>
              <span>High</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Tags</label>
            <Input
              placeholder="prod, sales (comma-separated)"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => addMut.mutate()}
            disabled={!content.trim() || addMut.isPending}
          >
            {addMut.isPending ? 'Saving…' : 'Add Memory'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Memory Card ───────────────────────────────────────────────────────────────

function MemoryCard({
  memory,
  onDelete,
  similarity,
}: {
  memory: Memory
  onDelete: () => void
  similarity?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const isLong = memory.content.length > 160

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-2 hover:border-border/80 transition-colors">
      <div className="flex items-start gap-3">
        {/* Importance bar */}
        <div className="flex flex-col items-center gap-1 shrink-0 pt-0.5">
          <div className="h-10 w-2 rounded-full bg-muted overflow-hidden flex flex-col-reverse">
            <div
              className={`w-full rounded-full transition-all ${importanceBg(memory.importance)}`}
              style={{ height: `${memory.importance * 100}%` }}
            />
          </div>
          <span className={`text-[10px] font-mono ${importanceText(memory.importance)}`}>
            {memory.importance.toFixed(2)}
          </span>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-1.5">
          <p className={`text-sm leading-relaxed ${!expanded && isLong ? 'line-clamp-2' : ''}`}>
            {memory.content}
          </p>
          {isLong && (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-0.5"
            >
              {expanded ? (
                <><ChevronUp className="h-3 w-3" /> Show less</>
              ) : (
                <><ChevronDown className="h-3 w-3" /> Show more</>
              )}
            </button>
          )}

          {similarity !== undefined && (
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full"
                  style={{ width: `${similarity * 100}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground font-mono shrink-0">
                {(similarity * 100).toFixed(0)}% match
              </span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5">
            {memory.tags.map((t) => (
              <span
                key={t}
                className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
              >
                {t}
              </span>
            ))}
            <span className="text-[11px] text-muted-foreground ml-auto">
              {fmtDate(memory.created_at)}
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={onDelete}
          className="shrink-0 p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
          title="Delete memory"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

// ── Episode Card ──────────────────────────────────────────────────────────────

function EpisodeCard({ agentId, episode }: { agentId: string; episode: Episode }) {
  const [expanded, setExpanded] = useState(false)

  const { data: detail, isLoading } = useQuery({
    queryKey: ['episode-detail', agentId, episode.id],
    queryFn: () => getEpisodeDetail(agentId, episode.id),
    enabled: expanded,
    staleTime: 60_000,
  })

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <button
        type="button"
        className="w-full flex items-start justify-between gap-3 p-4 hover:bg-accent/30 transition-colors text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{episode.title}</span>
            <Badge
              variant={episode.status === 'completed' ? 'success' : 'info'}
              className="text-xs shrink-0"
            >
              {episode.status}
            </Badge>
          </div>
          {episode.summary && (
            <p className="text-xs text-muted-foreground line-clamp-2">{episode.summary}</p>
          )}
          <p className="text-xs text-muted-foreground">
            Started {fmtDate(episode.started_at)}
            {episode.completed_at && ` · Completed ${fmtDate(episode.completed_at)}`}
          </p>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-border p-4 space-y-3">
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !detail ? null : (
            <>
              {detail.memories.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-2">
                  No memories in this episode
                </p>
              ) : (
                <div className="space-y-2">
                  {detail.memories.map((m) => (
                    <div
                      key={m.id}
                      className="flex items-start gap-2 text-sm p-2 rounded-md bg-muted/40"
                    >
                      <div
                        className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${importanceBg(m.importance)}`}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs line-clamp-2">{m.content}</p>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {fmtDate(m.created_at)} · imp {m.importance.toFixed(2)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                {detail.sessions.length} session{detail.sessions.length !== 1 ? 's' : ''}
                {' · '}
                {detail.memories.length} memor{detail.memories.length !== 1 ? 'ies' : 'y'}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tag filter dropdown ───────────────────────────────────────────────────────

function MemTagFilter({
  allTags,
  selected,
  onChange,
}: {
  allTags: string[]
  selected: string[]
  onChange: (t: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  if (allTags.length === 0) return null

  return (
    <div className="relative">
      <Button
        variant={selected.length > 0 ? 'secondary' : 'outline'}
        size="sm"
        className="h-7 text-xs"
        onClick={() => setOpen((p) => !p)}
      >
        Tags
        {selected.length > 0 && (
          <span className="ml-1 rounded-full bg-primary/20 px-1.5 py-0.5 text-[10px]">
            {selected.length}
          </span>
        )}
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-44 rounded-lg border border-border bg-background shadow-xl">
            <div className="p-1 max-h-48 overflow-y-auto">
              {allTags.map((tag) => (
                <label
                  key={tag}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-xs hover:bg-accent"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(tag)}
                    onChange={() =>
                      onChange(
                        selected.includes(tag)
                          ? selected.filter((t) => t !== tag)
                          : [...selected, tag],
                      )
                    }
                    className="accent-primary"
                  />
                  <span className="truncate">{tag}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── Short-term memory section ─────────────────────────────────────────────────

function ShortTermSection({ agentId }: { agentId: string }) {
  const qc = useQueryClient()
  const [sessionId, setSessionId] = useState('default')

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions', agentId],
    queryFn: () => listSessions({ agent_id: agentId }),
    staleTime: 30_000,
    retry: false,
  })

  const { data: shortMem, isLoading: shortLoading, refetch } = useQuery({
    queryKey: ['short-memory', agentId, sessionId],
    queryFn: () => getShortMemory(agentId, sessionId),
    staleTime: 15_000,
    retry: false,
  })

  const extractMut = useMutation({
    mutationFn: () => {
      const msgs = shortMem?.messages ?? []
      const conversation = msgs
        .map((m) => `${m.role}: ${m.content}`)
        .join('\n')
      return extractMemories(agentId, conversation, sessionId)
    },
    onSuccess: (result) => {
      toast.success(`Extracted ${result.extracted_count} memories`)
      void qc.invalidateQueries({ queryKey: ['memories', agentId] })
      void qc.invalidateQueries({ queryKey: ['memory-stats', agentId] })
    },
    onError: () => toast.error('Extraction failed'),
  })

  const activeSessions = sessions.filter((s) => s.status === 'active')

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          Short-term Memory
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className="h-7 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
          >
            <option value="default">default</option>
            {activeSessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id.slice(0, 8)}… (active)
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => void refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => extractMut.mutate()}
            disabled={!shortMem?.count || extractMut.isPending}
            title="Extract facts from this session into long-term memory"
          >
            <Zap className="h-3.5 w-3.5" />
            {extractMut.isPending ? 'Extracting…' : 'Extract Memories'}
          </Button>
        </div>
      </div>

      {shortLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 rounded-lg" />)}
        </div>
      ) : !shortMem || shortMem.messages.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center">
          <p className="text-sm text-muted-foreground">No messages in this session</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
          {shortMem.messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex gap-3 ${msg.role === 'assistant' ? 'flex-row-reverse' : ''}`}
            >
              <div
                className={`shrink-0 flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold uppercase
                  ${msg.role === 'assistant'
                    ? 'bg-primary/20 text-primary'
                    : 'bg-muted text-muted-foreground'
                  }`}
              >
                {msg.role[0]}
              </div>
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-xs
                  ${msg.role === 'assistant'
                    ? 'bg-primary/10 text-foreground'
                    : 'bg-muted text-foreground'
                  }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Memory Tab ───────────────────────────────────────────────────────────

export function MemoryTab({ agentId }: { agentId: string }) {
  const qc = useQueryClient()

  // View toggle
  const [view, setView] = useState<'memories' | 'episodes'>('memories')

  // Recall
  const [recallQuery, setRecallQuery] = useState('')
  const [minSim, setMinSim] = useState(0.5)
  const [recallResults, setRecallResults] = useState<Memory[] | null>(null)
  const [recallLoading, setRecallLoading] = useState(false)

  // Filters
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [impMin, setImpMin] = useState(0)
  const [impMax, setImpMax] = useState(1)
  const [sortBy, setSortBy] = useState<'importance' | 'created_at'>('importance')

  // Dialogs
  const [addOpen, setAddOpen] = useState(false)

  // Queries
  const { data: stats } = useQuery({
    queryKey: ['memory-stats', agentId],
    queryFn: () => getMemoryStats(agentId),
    staleTime: 30_000,
    retry: false,
  })

  const { data: memoriesData, isLoading: memLoading, refetch: refetchMem } = useQuery({
    queryKey: ['memories', agentId],
    queryFn: () => listMemories(agentId, { page_size: 100 }),
    staleTime: 30_000,
    enabled: view === 'memories',
    retry: false,
  })

  const { data: episodes = [], isLoading: epLoading } = useQuery({
    queryKey: ['episodes', agentId],
    queryFn: () => listEpisodes(agentId),
    staleTime: 60_000,
    enabled: view === 'episodes',
    retry: false,
  })

  const deleteMut = useMutation({
    mutationFn: (memId: string) => deleteMemory(agentId, memId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memories', agentId] })
      void qc.invalidateQueries({ queryKey: ['memory-stats', agentId] })
      toast.success('Memory deleted')
    },
    onError: () => toast.error('Failed to delete memory'),
  })

  // Collect all unique tags from loaded memories
  const allTags = useMemo(() => {
    const set = new Set<string>()
    memoriesData?.items.forEach((m) => m.tags.forEach((t) => set.add(t)))
    return [...set].sort()
  }, [memoriesData])

  // Filtered + sorted memories
  const filteredMemories = useMemo(() => {
    if (!memoriesData?.items) return []
    let list = memoriesData.items
    if (tagFilter.length > 0) {
      list = list.filter((m) => tagFilter.some((t) => m.tags.includes(t)))
    }
    list = list.filter((m) => m.importance >= impMin && m.importance <= impMax)
    if (sortBy === 'importance') {
      list = [...list].sort((a, b) => b.importance - a.importance)
    } else {
      list = [...list].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )
    }
    return list
  }, [memoriesData, tagFilter, impMin, impMax, sortBy])

  const hasFilters = tagFilter.length > 0 || impMin > 0 || impMax < 1

  async function handleRecall() {
    if (!recallQuery.trim()) return
    setRecallLoading(true)
    setRecallResults(null)
    try {
      const res = await recallMemories(agentId, recallQuery.trim(), 10, minSim)
      setRecallResults(res.results)
    } catch {
      toast.error('Recall failed')
    } finally {
      setRecallLoading(false)
    }
  }

  return (
    <div className="space-y-6 pt-4">
      {/* ── Stats ── */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Active', value: stats.total_active, icon: Brain, color: 'text-blue-400' },
            { label: 'Archived', value: stats.total_archived, icon: Archive, color: 'text-muted-foreground' },
            {
              label: 'Avg Importance',
              value: stats.avg_importance.toFixed(2),
              icon: Zap,
              color: importanceText(stats.avg_importance),
            },
            {
              label: 'Most Accessed',
              value: stats.most_accessed_memory
                ? `${stats.most_accessed_memory.access_count}×`
                : '—',
              icon: RefreshCw,
              color: 'text-muted-foreground',
            },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className={`h-3.5 w-3.5 ${color}`} />
                <span className="text-xs text-muted-foreground">{label}</span>
              </div>
              <div className="text-lg font-bold tabular-nums">{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Recall ── */}
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Search className="h-4 w-4 text-muted-foreground" />
          Semantic Recall
        </h3>
        <div className="flex gap-2">
          <Input
            placeholder="What do you want to recall?"
            value={recallQuery}
            onChange={(e) => setRecallQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void handleRecall()}
            className="flex-1"
          />
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              min {minSim.toFixed(1)}
            </span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={minSim}
              onChange={(e) => setMinSim(parseFloat(e.target.value))}
              className="w-20 accent-primary cursor-pointer"
            />
          </div>
          <Button
            onClick={() => void handleRecall()}
            disabled={!recallQuery.trim() || recallLoading}
            size="sm"
          >
            {recallLoading ? '…' : 'Search'}
          </Button>
          {recallResults !== null && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => { setRecallResults(null); setRecallQuery('') }}
              title="Clear results"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>

        {recallResults !== null && (
          <div className="space-y-2 mt-2">
            {recallResults.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-3">
                No results above the similarity threshold
              </p>
            ) : (
              recallResults.map((m) => (
                <MemoryCard
                  key={m.id}
                  memory={m}
                  similarity={m.similarity ?? undefined}
                  onDelete={() => deleteMut.mutate(m.id)}
                />
              ))
            )}
          </div>
        )}
      </div>

      {/* ── Long-term / Episodes toggle ── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-muted/30">
            <Button
              variant={view === 'memories' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setView('memories')}
            >
              <Brain className="h-3.5 w-3.5 mr-1" />
              Long-term
            </Button>
            <Button
              variant={view === 'episodes' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setView('episodes')}
            >
              <BookOpen className="h-3.5 w-3.5 mr-1" />
              Episodes
            </Button>
          </div>

          {view === 'memories' && (
            <Button size="sm" className="h-7 text-xs" onClick={() => setAddOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              Add Memory
            </Button>
          )}
        </div>

        {/* Memories view */}
        {view === 'memories' && (
          <>
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <MemTagFilter allTags={allTags} selected={tagFilter} onChange={setTagFilter} />

              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Imp:</span>
                <span className="text-xs font-mono">{impMin.toFixed(1)}</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={impMin}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value)
                    setImpMin(Math.min(v, impMax))
                  }}
                  className="w-16 accent-primary cursor-pointer"
                />
                <span className="text-xs text-muted-foreground">–</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={impMax}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value)
                    setImpMax(Math.max(v, impMin))
                  }}
                  className="w-16 accent-primary cursor-pointer"
                />
                <span className="text-xs font-mono">{impMax.toFixed(1)}</span>
              </div>

              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as 'importance' | 'created_at')}
                className="h-7 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="importance">By importance</option>
                <option value="created_at">By date</option>
              </select>

              {hasFilters && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  onClick={() => {
                    setTagFilter([])
                    setImpMin(0)
                    setImpMax(1)
                  }}
                >
                  <X className="h-3 w-3" />
                  Clear
                </Button>
              )}

              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 ml-auto"
                onClick={() => void refetchMem()}
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>

            {/* Memory list */}
            {memLoading ? (
              <div className="space-y-2">
                {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
              </div>
            ) : filteredMemories.length === 0 ? (
              <EmptyState
                icon={Brain}
                title={hasFilters ? 'No memories match your filters' : 'No memories yet'}
                description={
                  hasFilters
                    ? 'Adjust the filters or clear them.'
                    : 'Add a memory above or let the agent create them automatically.'
                }
                action={
                  hasFilters ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setTagFilter([])
                        setImpMin(0)
                        setImpMax(1)
                      }}
                    >
                      Clear filters
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground mb-2">
                  {filteredMemories.length} memor{filteredMemories.length !== 1 ? 'ies' : 'y'}
                  {hasFilters && ' (filtered)'}
                </p>
                {filteredMemories.map((m) => (
                  <MemoryCard
                    key={m.id}
                    memory={m}
                    onDelete={() => deleteMut.mutate(m.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* Episodes view */}
        {view === 'episodes' && (
          <>
            {epLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
              </div>
            ) : episodes.length === 0 ? (
              <EmptyState
                icon={BookOpen}
                title="No episodes yet"
                description="Episodes group related sessions and their extracted memories."
              />
            ) : (
              <div className="space-y-2">
                {episodes.map((ep) => (
                  <EpisodeCard key={ep.id} agentId={agentId} episode={ep} />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Separator ── */}
      <div className="border-t border-border" />

      {/* ── Short-term ── */}
      <ShortTermSection agentId={agentId} />

      {/* Add Memory Dialog */}
      <AddMemoryDialog
        agentId={agentId}
        open={addOpen}
        onClose={() => setAddOpen(false)}
      />
    </div>
  )
}
