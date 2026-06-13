import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Check,
  RotateCcw,
  ChevronRight,
  FileText,
  Zap,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  listPromptVersions,
  createPromptVersion,
  activatePromptVersion,
  rollbackPrompt,
  diffPromptVersions,
} from '@/api/prompts'
import { getEvaluationSummary, listABTests } from '@/api/evaluations'
import { getActionStats } from '@/api/actions'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime, formatNumber } from '@/lib/formatters'
import type { PromptVersion, DiffLine } from '@/types/api'

// ── Diff view ─────────────────────────────────────────────────────────────────

function DiffView({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 overflow-auto max-h-80 font-mono text-xs">
      {lines.map((line, i) => (
        <div
          key={i}
          className={`flex gap-3 px-3 py-0.5 leading-5 ${
            line.operation === 'insert'
              ? 'bg-emerald-950/40 text-emerald-300'
              : line.operation === 'delete'
              ? 'bg-red-950/40 text-red-300 line-through'
              : 'text-muted-foreground'
          }`}
        >
          <span className="select-none w-8 shrink-0 text-right opacity-50">
            {line.operation === 'insert' ? line.line_b : line.line_a}
          </span>
          <span className="select-none w-4 shrink-0">
            {line.operation === 'insert' ? '+' : line.operation === 'delete' ? '-' : ' '}
          </span>
          <span className="whitespace-pre-wrap break-all flex-1">{line.content}</span>
        </div>
      ))}
    </div>
  )
}

// ── Prompt content viewer with syntax-ish highlighting ────────────────────────

function PromptContent({ content }: { content: string }) {
  return (
    <pre className="rounded-md border border-border bg-muted/20 p-4 text-xs font-mono leading-5 overflow-auto max-h-96 whitespace-pre-wrap break-words text-foreground/90">
      {content}
    </pre>
  )
}

// ── Version metrics ───────────────────────────────────────────────────────────

function VersionMetrics({ agentId }: { agentId: string }) {
  const { data: stats } = useQuery({
    queryKey: ['agent-stats', agentId],
    queryFn: () => getActionStats(agentId),
    staleTime: 60_000,
    retry: false,
  })
  const { data: summary } = useQuery({
    queryKey: ['eval-summary', agentId],
    queryFn: () => getEvaluationSummary(agentId),
    staleTime: 60_000,
    retry: false,
  })

  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="rounded-md border border-border bg-muted/20 p-3 text-center">
        <p className="text-xs text-muted-foreground">Total Actions</p>
        <p className="text-lg font-bold tabular-nums">{stats ? formatNumber(stats.total_actions) : '—'}</p>
      </div>
      <div className="rounded-md border border-border bg-muted/20 p-3 text-center">
        <p className="text-xs text-muted-foreground">Avg Score</p>
        <p className="text-lg font-bold tabular-nums text-amber-400">
          {summary?.avg_score != null ? summary.avg_score.toFixed(2) : '—'}
        </p>
      </div>
      <div className="rounded-md border border-border bg-muted/20 p-3 text-center">
        <p className="text-xs text-muted-foreground">Eval count</p>
        <p className="text-lg font-bold tabular-nums">{summary ? formatNumber(summary.total_evaluations) : '—'}</p>
      </div>
    </div>
  )
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function VersionPanel({
  agentId,
  version,
  allVersions,
  activeVersion,
  onClose,
}: {
  agentId: string
  version: PromptVersion
  allVersions: PromptVersion[]
  activeVersion: PromptVersion | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [diffTargetId, setDiffTargetId] = useState('')
  const [confirmActivate, setConfirmActivate] = useState(false)

  const { data: abTests } = useQuery({
    queryKey: ['ab-tests', agentId],
    queryFn: () => listABTests(agentId),
    staleTime: 60_000,
    retry: false,
  })
  const hasActiveTest = abTests?.items.some(t => t.status === 'active') ?? false

  const { data: diffData, isLoading: diffLoading } = useQuery({
    queryKey: ['prompt-diff', agentId, version.id, diffTargetId],
    queryFn: () => diffPromptVersions(agentId, version.id, diffTargetId),
    enabled: !!diffTargetId,
    staleTime: 60_000,
    retry: false,
  })

  const activateMut = useMutation({
    mutationFn: () => activatePromptVersion(agentId, version.id),
    onSuccess: () => {
      toast.success(`v${version.version} activated`)
      void qc.invalidateQueries({ queryKey: ['prompts', agentId] })
      setConfirmActivate(false)
    },
    onError: () => toast.error('Failed to activate version'),
  })

  const rollbackMut = useMutation({
    mutationFn: () => rollbackPrompt(agentId),
    onSuccess: () => {
      toast.success('Rolled back to previous version')
      void qc.invalidateQueries({ queryKey: ['prompts', agentId] })
    },
    onError: () => toast.error('Rollback failed'),
  })

  const isActive = version.is_active
  const activeIdx = allVersions.findIndex(v => v.is_active)
  const thisIdx = allVersions.findIndex(v => v.id === version.id)
  const isImmediatePrev = activeIdx !== -1 && thisIdx === activeIdx + 1
  const otherVersions = allVersions.filter(v => v.id !== version.id)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between pb-3 border-b border-border mb-4">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-sm">v{version.version}</h3>
          {isActive && <Badge variant="success" className="text-xs">Active</Badge>}
        </div>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground text-xs">✕ Close</button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4">
        {version.description && (
          <p className="text-sm text-muted-foreground italic">{version.description}</p>
        )}

        <PromptContent content={version.content} />

        <VersionMetrics agentId={agentId} />

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          {!isActive && (
            confirmActivate ? (
              <div className="flex items-center gap-2">
                {hasActiveTest && <p className="text-xs text-amber-400">⚠ Active A/B test will be affected</p>}
                <Button size="sm" onClick={() => activateMut.mutate()} disabled={activateMut.isPending}>
                  {activateMut.isPending ? 'Activating…' : 'Confirm Activate'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmActivate(false)}>Cancel</Button>
              </div>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setConfirmActivate(true)}>
                <Zap className="h-3.5 w-3.5 mr-1.5" />Activate
              </Button>
            )
          )}
          {isImmediatePrev && (
            <Button size="sm" variant="outline" onClick={() => rollbackMut.mutate()} disabled={rollbackMut.isPending}>
              <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
              {rollbackMut.isPending ? 'Rolling back…' : 'Rollback to this'}
            </Button>
          )}
        </div>

        {/* Diff selector */}
        {otherVersions.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium">Compare with:</label>
              <select
                value={diffTargetId}
                onChange={e => setDiffTargetId(e.target.value)}
                className="h-7 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">— select version —</option>
                {otherVersions.map(v => (
                  <option key={v.id} value={v.id}>v{v.version}{v.is_active ? ' (active)' : ''}</option>
                ))}
              </select>
            </div>
            {diffTargetId && (
              diffLoading
                ? <Skeleton className="h-32 w-full" />
                : diffData && <DiffView lines={diffData.lines} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── New version modal ─────────────────────────────────────────────────────────

function NewVersionModal({
  agentId,
  activeContent,
  open,
  onClose,
}: {
  agentId: string
  activeContent: string
  open: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [content, setContent] = useState(activeContent)
  const [description, setDescription] = useState('')

  const createMut = useMutation({
    mutationFn: () =>
      createPromptVersion(agentId, {
        content: content.trim(),
        description: description.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success('New version created')
      void qc.invalidateQueries({ queryKey: ['prompts', agentId] })
      onClose()
    },
    onError: () => toast.error('Failed to create version'),
  })

  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New Prompt Version</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Description of change</label>
            <Input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="What changed and why?"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Content</label>
            <Textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={12}
              className="font-mono text-xs resize-y"
              placeholder="System prompt content…"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <Button
              className="flex-1"
              disabled={!content.trim() || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {createMut.isPending ? 'Creating…' : 'Create Version'}
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Main tab ─────────────────────────────────────────────────────────────────

export function PromptsTab({ agentId }: { agentId: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [newOpen, setNewOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['prompts', agentId],
    queryFn: () => listPromptVersions(agentId),
    staleTime: 30_000,
  })

  const versions = data?.items ?? []
  const activeVersion = versions.find(v => v.is_active) ?? null
  const selectedVersion = versions.find(v => v.id === selectedId) ?? null

  const activeContent = activeVersion?.content ?? ''

  if (isLoading) {
    return (
      <div className="space-y-2 py-4">
        {[0,1,2].map(i => <Skeleton key={i} className="h-16 w-full" />)}
      </div>
    )
  }

  return (
    <div className="py-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold">Prompt Versions</h3>
        <Button size="sm" variant="outline" onClick={() => setNewOpen(true)}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />New Version
        </Button>
      </div>

      {versions.length === 0 ? (
        <EmptyState icon={FileText} title="No prompt versions" description="Create a first version to start managing prompts." action={<Button size="sm" onClick={() => setNewOpen(true)}>Create first version</Button>} />
      ) : (
        <div className={`flex gap-6 ${selectedVersion ? 'lg:flex-row' : ''}`}>
          {/* Version list */}
          <div className={`space-y-1.5 ${selectedVersion ? 'lg:w-64 lg:shrink-0' : 'w-full'}`}>
            {versions.map(v => (
              <button
                key={v.id}
                type="button"
                onClick={() => setSelectedId(selectedId === v.id ? null : v.id)}
                className={`w-full rounded-lg border p-3 text-left transition-colors flex items-center gap-3 group ${selectedId === v.id ? 'border-primary bg-primary/5' : 'border-border hover:border-muted-foreground/50 bg-background'}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">v{v.version}</span>
                    {v.is_active && <Badge variant="success" className="text-[10px] px-1.5 py-0">Active</Badge>}
                  </div>
                  {v.description && <p className="text-xs text-muted-foreground truncate mt-0.5">{v.description}</p>}
                  <p className="text-xs text-muted-foreground">{formatRelativeTime(v.created_at)}</p>
                </div>
                <ChevronRight className={`h-4 w-4 text-muted-foreground shrink-0 transition-transform ${selectedId === v.id ? 'rotate-90' : 'opacity-0 group-hover:opacity-100'}`} />
              </button>
            ))}
          </div>

          {/* Detail panel */}
          {selectedVersion && (
            <div className="flex-1 min-w-0 rounded-lg border border-border bg-background p-4">
              <VersionPanel
                agentId={agentId}
                version={selectedVersion}
                allVersions={versions}
                activeVersion={activeVersion}
                onClose={() => setSelectedId(null)}
              />
            </div>
          )}
        </div>
      )}

      <NewVersionModal
        agentId={agentId}
        activeContent={activeContent}
        open={newOpen}
        onClose={() => setNewOpen(false)}
      />
    </div>
  )
}
