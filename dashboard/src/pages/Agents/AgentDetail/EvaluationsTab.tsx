import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Star,
  ThumbsUp,
  ThumbsDown,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Plus,
  CheckCircle2,
  X,
} from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import { subDays, format, parseISO } from 'date-fns'
import { toast } from 'sonner'

import {
  getEvaluationSummary,
  listEvaluations,
  listAnomalies,
  resolveAnomaly,
  listABTests,
  getABTestResults,
  createABTest,
  completeABTest,
} from '@/api/evaluations'
import { listPromptVersions } from '@/api/prompts'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime, formatDate } from '@/lib/formatters'
import type { ABTest, ABTestWinner } from '@/types/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

const CHART = {
  grid: 'hsl(217.2 32.6% 17.5%)',
  tick: { fontSize: 11, fill: 'hsl(215 20.2% 55%)' },
  tooltip: {
    contentStyle: {
      backgroundColor: 'hsl(222.2 84% 5%)',
      border: '1px solid hsl(217.2 32.6% 17.5%)',
      borderRadius: 6,
      fontSize: 12,
    },
  },
} as const

const SEVERITY_VARIANT: Record<string, 'error' | 'warning' | 'secondary'> = {
  high: 'error',
  medium: 'warning',
  low: 'secondary',
}

function Stars({ score }: { score: number }) {
  const full = Math.round(score)
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map(i => (
        <Star
          key={i}
          className={`h-4 w-4 ${i <= full ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/30'}`}
        />
      ))}
    </div>
  )
}

// ── A/B Test Results inline ───────────────────────────────────────────────────

function ABTestResults({ agentId, testId }: { agentId: string; testId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['ab-results', agentId, testId],
    queryFn: () => getABTestResults(agentId, testId),
    staleTime: 30_000,
    retry: false,
  })

  if (isLoading) return <div className="py-2"><Skeleton className="h-16 w-full" /></div>
  if (!data) return null

  const a = data.variant_a
  const b = data.variant_b
  const aScore = a.avg_score ?? 0
  const bScore = b.avg_score ?? 0
  const maxActions = Math.max(a.total_actions, b.total_actions, 1)

  return (
    <div className="mt-3 grid grid-cols-2 gap-3">
      {[a, b].map(v => (
        <div key={v.variant} className="rounded-md border border-border bg-muted/20 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide">Variant {v.variant.toUpperCase()}</span>
            {v.avg_score != null && <span className="text-xs text-amber-400 font-mono">{v.avg_score.toFixed(2)} / 5</span>}
          </div>
          <div className="text-xs text-muted-foreground space-y-1">
            <div className="flex justify-between">
              <span>Actions</span>
              <div className="flex items-center gap-2">
                <div className="w-16 h-1 rounded-full bg-muted overflow-hidden">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(v.total_actions / maxActions) * 100}%` }} />
                </div>
                <span className="font-mono">{v.total_actions}</span>
              </div>
            </div>
            <div className="flex justify-between">
              <span>👍 Ratio</span>
              <span className={`font-mono ${v.thumbs_up_ratio >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>{(v.thumbs_up_ratio * 100).toFixed(0)}%</span>
            </div>
            <div className="flex justify-between">
              <span>Error rate</span>
              <span className={`font-mono ${v.error_rate > 0.1 ? 'text-red-400' : 'text-muted-foreground'}`}>{(v.error_rate * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      ))}
      {aScore !== bScore && (
        <div className="col-span-2 text-xs text-center text-muted-foreground">
          {aScore > bScore
            ? <span className="text-emerald-400">Variant A is leading (+{(aScore - bScore).toFixed(2)} score)</span>
            : <span className="text-emerald-400">Variant B is leading (+{(bScore - aScore).toFixed(2)} score)</span>}
        </div>
      )}
    </div>
  )
}

// ── Complete A/B Test modal ───────────────────────────────────────────────────

function CompleteTestModal({
  agentId,
  test,
  open,
  onClose,
}: {
  agentId: string
  test: ABTest
  open: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [winner, setWinner] = useState<ABTestWinner>('inconclusive')

  const completeMut = useMutation({
    mutationFn: () => completeABTest(agentId, test.id, winner),
    onSuccess: () => {
      toast.success('A/B test completed')
      void qc.invalidateQueries({ queryKey: ['ab-tests', agentId] })
      onClose()
    },
    onError: () => toast.error('Failed to complete test'),
  })

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Complete A/B Test</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">Select the winning variant or mark as inconclusive. If a winner is chosen, that prompt version will be activated.</p>
          <div className="grid grid-cols-3 gap-2">
            {(['a', 'b', 'inconclusive'] as ABTestWinner[]).map(w => (
              <button
                key={w}
                type="button"
                onClick={() => setWinner(w)}
                className={`rounded-lg border p-3 text-sm font-medium transition-colors capitalize ${winner === w ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:border-muted-foreground'}`}
              >
                {w === 'a' ? 'Variant A' : w === 'b' ? 'Variant B' : 'Inconclusive'}
              </button>
            ))}
          </div>
          <div className="flex gap-2 pt-2">
            <Button className="flex-1" onClick={() => completeMut.mutate()} disabled={completeMut.isPending}>
              {completeMut.isPending ? 'Completing…' : 'Complete Test'}
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── New A/B Test modal ────────────────────────────────────────────────────────

function NewABTestModal({
  agentId,
  open,
  onClose,
}: {
  agentId: string
  open: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [variantA, setVariantA] = useState('')
  const [variantB, setVariantB] = useState('')
  const [split, setSplit] = useState(50)

  const { data: prompts } = useQuery({
    queryKey: ['prompts', agentId],
    queryFn: () => listPromptVersions(agentId),
    staleTime: 60_000,
  })

  const createMut = useMutation({
    mutationFn: () =>
      createABTest(agentId, {
        name: name.trim(),
        variant_a_prompt_version_id: variantA,
        variant_b_prompt_version_id: variantB,
        traffic_split: split / 100,
      }),
    onSuccess: () => {
      toast.success('A/B test created')
      void qc.invalidateQueries({ queryKey: ['ab-tests', agentId] })
      setName(''); setVariantA(''); setVariantB(''); setSplit(50)
      onClose()
    },
    onError: () => toast.error('Failed to create A/B test'),
  })

  const versions = prompts?.items ?? []
  const canSubmit = name.trim() && variantA && variantB && variantA !== variantB

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New A/B Test</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Test Name</label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Concise vs Verbose" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Variant A</label>
              <select
                value={variantA}
                onChange={e => setVariantA(e.target.value)}
                className="w-full h-9 rounded-md border border-border bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">— select version —</option>
                {versions.map(v => (
                  <option key={v.id} value={v.id}>v{v.version}{v.is_active ? ' (active)' : ''}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Variant B</label>
              <select
                value={variantB}
                onChange={e => setVariantB(e.target.value)}
                className="w-full h-9 rounded-md border border-border bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">— select version —</option>
                {versions.map(v => (
                  <option key={v.id} value={v.id}>v{v.version}{v.is_active ? ' (active)' : ''}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <label className="font-medium">Traffic Split</label>
              <span className="text-muted-foreground font-mono">{split}% A · {100 - split}% B</span>
            </div>
            <input
              type="range" min="10" max="90" step="5" value={split}
              onChange={e => setSplit(Number(e.target.value))}
              className="w-full accent-primary"
            />
            <div className="h-2 rounded-full overflow-hidden bg-muted flex">
              <div className="h-full bg-sky-500 transition-all" style={{ width: `${split}%` }} />
              <div className="h-full bg-violet-500 flex-1 transition-all" />
            </div>
          </div>
          <div className="flex gap-2 pt-2">
            <Button className="flex-1" disabled={!canSubmit || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? 'Creating…' : 'Create Test'}
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── A/B Tests section ─────────────────────────────────────────────────────────

function ABTestsSection({ agentId }: { agentId: string }) {
  const [newOpen, setNewOpen] = useState(false)
  const [completeTarget, setCompleteTarget] = useState<ABTest | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['ab-tests', agentId],
    queryFn: () => listABTests(agentId),
    staleTime: 30_000,
    retry: false,
  })

  const tests = data?.items ?? []
  const active = tests.filter(t => t.status === 'active')
  const done = tests.filter(t => t.status !== 'active')

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">A/B Tests</h3>
        <Button size="sm" variant="outline" onClick={() => setNewOpen(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" />New Test
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">{[0, 1].map(i => <Skeleton key={i} className="h-20" />)}</div>
      ) : tests.length === 0 ? (
        <p className="text-sm text-muted-foreground">No A/B tests yet.</p>
      ) : (
        <div className="space-y-2">
          {active.length > 0 && (
            <>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Active</p>
              {active.map(test => (
                <Card key={test.id}>
                  <CardContent className="p-4 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{test.name}</span>
                          <Badge variant="warning" className="text-xs">active</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Started {formatRelativeTime(test.started_at)} · Split {Math.round(test.traffic_split * 100)}% A / {Math.round((1 - test.traffic_split) * 100)}% B
                        </p>
                      </div>
                      <div className="flex gap-1.5 shrink-0">
                        <Button
                          size="sm" variant="ghost" className="h-7 text-xs"
                          onClick={() => setExpandedId(expandedId === test.id ? null : test.id)}
                        >
                          {expandedId === test.id ? 'Hide' : 'Results'}
                        </Button>
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setCompleteTarget(test)}>
                          Complete
                        </Button>
                      </div>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden bg-muted flex">
                      <div className="h-full bg-sky-500" style={{ width: `${test.traffic_split * 100}%` }} />
                      <div className="h-full bg-violet-500 flex-1" />
                    </div>
                    {expandedId === test.id && <ABTestResults agentId={agentId} testId={test.id} />}
                  </CardContent>
                </Card>
              ))}
            </>
          )}
          {done.length > 0 && (
            <>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mt-2">Completed</p>
              {done.map(test => (
                <Card key={test.id}>
                  <CardContent className="flex items-center gap-4 p-4">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-sm">{test.name}</span>
                      <div className="flex items-center gap-2 mt-0.5">
                        {test.winner && test.winner !== 'inconclusive'
                          ? <span className="text-xs text-muted-foreground">Winner: <span className="text-emerald-400 font-medium">Variant {test.winner.toUpperCase()}</span></span>
                          : <span className="text-xs text-muted-foreground">Inconclusive</span>
                        }
                        {test.completed_at && <span className="text-xs text-muted-foreground">· {formatDate(test.completed_at)}</span>}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </>
          )}
        </div>
      )}

      <NewABTestModal agentId={agentId} open={newOpen} onClose={() => setNewOpen(false)} />
      {completeTarget && (
        <CompleteTestModal
          agentId={agentId}
          test={completeTarget}
          open={!!completeTarget}
          onClose={() => setCompleteTarget(null)}
        />
      )}
    </div>
  )
}

// ── Main tab ─────────────────────────────────────────────────────────────────

export function EvaluationsTab({ agentId }: { agentId: string }) {
  const qc = useQueryClient()

  const since30 = useMemo(() => subDays(new Date(), 30).toISOString().split('T')[0], [])
  const since14 = useMemo(() => subDays(new Date(), 14).toISOString().split('T')[0], [])
  const since7  = useMemo(() => subDays(new Date(), 7).toISOString().split('T')[0], [])

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['eval-summary', agentId],
    queryFn: () => getEvaluationSummary(agentId),
    staleTime: 30_000,
    retry: false,
  })

  const { data: evals30 } = useQuery({
    queryKey: ['evals-30d', agentId],
    queryFn: () => listEvaluations(agentId, { from_date: since30, limit: 500 }),
    staleTime: 60_000,
    retry: false,
  })

  const { data: anomalies, isLoading: anomalyLoading } = useQuery({
    queryKey: ['anomalies', agentId, false],
    queryFn: () => listAnomalies(agentId, false),
    staleTime: 30_000,
    retry: false,
  })

  const resolveMut = useMutation({
    mutationFn: (anomalyId: string) => resolveAnomaly(agentId, anomalyId),
    onSuccess: () => {
      toast.success('Anomaly resolved')
      void qc.invalidateQueries({ queryKey: ['anomalies', agentId] })
    },
    onError: () => toast.error('Failed to resolve anomaly'),
  })

  // Build 30-day line chart from fetched evaluations
  const chart30d = useMemo(() => {
    const days: Record<string, { day: string; avg_score: number | null; count: number; _scores: number[] }> = {}
    for (let i = 29; i >= 0; i--) {
      const d = format(subDays(new Date(), i), 'yyyy-MM-dd')
      days[d] = { day: format(subDays(new Date(), i), 'MMM d'), avg_score: null, count: 0, _scores: [] }
    }
    evals30?.items.forEach(e => {
      const d = e.created_at.split('T')[0]
      if (days[d]) {
        days[d].count++
        if (e.rating_score != null) days[d]._scores.push(e.rating_score)
      }
    })
    return Object.values(days).map(d => ({
      ...d,
      avg_score: d._scores.length > 0 ? d._scores.reduce((a, b) => a + b, 0) / d._scores.length : null,
    }))
  }, [evals30])

  // Trend: compare last 7d vs 7d before
  const trend = useMemo(() => {
    if (!summary) return 0
    const t = summary.trend_7d
    const last7 = t.slice(-7)
    const prev7 = t.slice(0, 7)
    const avgLast = last7.filter(d => d.avg_score != null).reduce((a, d) => a + (d.avg_score ?? 0), 0) / Math.max(last7.filter(d => d.avg_score != null).length, 1)
    const avgPrev = prev7.filter(d => d.avg_score != null).reduce((a, d) => a + (d.avg_score ?? 0), 0) / Math.max(prev7.filter(d => d.avg_score != null).length, 1)
    return avgLast - avgPrev
  }, [summary])

  const thumbsTotal = (summary?.thumbs_up ?? 0) + (summary?.thumbs_down ?? 0)
  const donutData = thumbsTotal > 0
    ? [
        { name: 'Up', value: summary?.thumbs_up ?? 0, color: 'hsl(142 71% 45%)' },
        { name: 'Down', value: summary?.thumbs_down ?? 0, color: 'hsl(0 62.8% 50%)' },
      ]
    : [{ name: 'None', value: 1, color: 'hsl(217.2 32.6% 17.5%)' }]

  if (summaryLoading) {
    return (
      <div className="space-y-4 py-4">
        <div className="grid grid-cols-4 gap-3">{[0,1,2,3].map(i => <Skeleton key={i} className="h-24" />)}</div>
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (!summary || summary.total_evaluations === 0) {
    return <EmptyState icon={Star} title="No evaluations yet" description="Evaluations appear after actions receive ratings." />
  }

  return (
    <div className="space-y-6 py-4">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card>
          <CardContent className="p-4 space-y-2">
            <p className="text-xs text-muted-foreground">Avg Score</p>
            {summary.avg_score != null ? (
              <>
                <div className="text-2xl font-bold tabular-nums">{summary.avg_score.toFixed(2)}</div>
                <Stars score={summary.avg_score} />
              </>
            ) : <span className="text-muted-foreground text-sm">N/A</span>}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <PieChart width={56} height={56}>
              <Pie data={donutData} cx={24} cy={24} innerRadius={16} outerRadius={26} dataKey="value" startAngle={90} endAngle={-270}>
                {donutData.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Pie>
            </PieChart>
            <div>
              <p className="text-xs text-muted-foreground">Thumbs</p>
              <div className="flex items-center gap-1.5">
                <ThumbsUp className="h-3.5 w-3.5 text-emerald-400" />
                <span className="text-sm font-bold text-emerald-400">{summary.thumbs_up}</span>
                <ThumbsDown className="h-3.5 w-3.5 text-red-400 ml-1" />
                <span className="text-sm font-bold text-red-400">{summary.thumbs_down}</span>
              </div>
              <p className="text-xs text-muted-foreground">{(summary.thumbs_up_ratio * 100).toFixed(0)}% positive</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Total Evaluations</p>
            <div className="text-2xl font-bold tabular-nums">{summary.total_evaluations}</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Trend (7d vs prev 7d)</p>
            <div className={`flex items-center gap-2 ${trend > 0 ? 'text-emerald-400' : trend < 0 ? 'text-red-400' : 'text-muted-foreground'}`}>
              {trend > 0 ? <TrendingUp className="h-5 w-5" /> : trend < 0 ? <TrendingDown className="h-5 w-5" /> : <Minus className="h-5 w-5" />}
              <span className="text-2xl font-bold tabular-nums">
                {trend === 0 ? '—' : `${trend > 0 ? '+' : ''}${trend.toFixed(2)}`}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 30-day chart */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Score trend — last 30 days</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chart30d}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
              <XAxis dataKey="day" tick={CHART.tick} tickLine={false} axisLine={false} interval={4} />
              <YAxis yAxisId="score" domain={[0, 5]} tick={CHART.tick} tickLine={false} axisLine={false} />
              <YAxis yAxisId="count" orientation="right" tick={CHART.tick} tickLine={false} axisLine={false} />
              <Tooltip {...CHART.tooltip} />
              <Line yAxisId="score" type="monotone" dataKey="avg_score" stroke="hsl(142 71% 45%)" strokeWidth={2} dot={false} name="Avg Score" connectNulls />
              <Line yAxisId="count" type="monotone" dataKey="count" stroke="hsl(217.2 91.2% 59.8%)" strokeWidth={1.5} dot={false} name="Count" strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground justify-end">
            <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-emerald-400 rounded" />Avg Score</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-blue-400 rounded border-dashed" />Count</span>
          </div>
        </CardContent>
      </Card>

      {/* By prompt version */}
      {summary.by_prompt_version.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">By Prompt Version</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-muted/30">
                <tr>
                  <th className="px-4 py-2 text-left text-xs text-muted-foreground font-medium">Version</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">Evaluations</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">Avg Score</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">👍 Ratio</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_prompt_version.map((v, i) => (
                  <tr key={v.prompt_version_id ?? i} className="border-b border-border/50">
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                      {v.prompt_version_id ? v.prompt_version_id.slice(0, 8) + '…' : 'unlinked'}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs">{v.count}</td>
                    <td className="px-4 py-2.5 text-right">
                      {v.avg_score != null
                        ? <span className="text-xs font-mono text-amber-400">{v.avg_score.toFixed(2)}</span>
                        : <span className="text-xs text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={`text-xs font-mono ${((v.thumbs_up) / Math.max(v.thumbs_up + v.thumbs_down, 1)) >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {v.thumbs_up + v.thumbs_down > 0
                          ? `${((v.thumbs_up / (v.thumbs_up + v.thumbs_down)) * 100).toFixed(0)}%`
                          : '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Anomalies */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Open Anomalies</h3>
        {anomalyLoading ? (
          <div className="space-y-2">{[0,1].map(i => <Skeleton key={i} className="h-14" />)}</div>
        ) : (anomalies?.items.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">No unresolved anomalies.</p>
        ) : (
          <div className="space-y-2">
            {anomalies!.items.map(a => (
              <Card key={a.id}>
                <CardContent className="flex items-center gap-4 p-4">
                  <AlertTriangle className={`h-5 w-5 shrink-0 ${a.severity === 'high' ? 'text-red-400' : a.severity === 'medium' ? 'text-amber-400' : 'text-muted-foreground'}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{String(a.anomaly_type)}</span>
                      <Badge variant={SEVERITY_VARIANT[a.severity] ?? 'secondary'} className="text-xs">{a.severity}</Badge>
                    </div>
                    {Object.keys(a.details ?? {}).length > 0 && (
                      <p className="text-xs text-muted-foreground mt-0.5 truncate">
                        {Object.entries(a.details).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">{formatRelativeTime(a.created_at)}</p>
                  </div>
                  <Button
                    size="sm" variant="outline"
                    onClick={() => resolveMut.mutate(a.id)}
                    disabled={resolveMut.isPending}
                    className="shrink-0 h-7 text-xs"
                  >
                    <X className="h-3 w-3 mr-1" />Resolve
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* A/B Tests */}
      <ABTestsSection agentId={agentId} />
    </div>
  )
}
