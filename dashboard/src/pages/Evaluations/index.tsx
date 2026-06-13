import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query'
import {
  Star,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  X,
  CheckCircle2,
  BarChart3,
} from 'lucide-react'
import {
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { subDays, format } from 'date-fns'
import { toast } from 'sonner'

import { listAgents } from '@/api/agents'
import {
  getEvaluationSummary,
  listEvaluations,
  listAnomalies,
  resolveAnomaly,
  listABTests,
} from '@/api/evaluations'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'
import type { Agent, EvaluationSummary, DayTrend } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────

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
        <Star key={i} className={`h-3.5 w-3.5 ${i <= full ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/30'}`} />
      ))}
    </div>
  )
}

// Sparkline of 7d trend
function Sparkline({ data }: { data: DayTrend[] }) {
  const pts = data.map((d, i) => ({ i, v: d.avg_score ?? 0 }))
  if (pts.every(p => p.v === 0)) return <span className="text-xs text-muted-foreground">—</span>
  return (
    <ResponsiveContainer width={80} height={28}>
      <LineChart data={pts}>
        <Tooltip
          contentStyle={{ fontSize: 10, padding: '2px 6px', backgroundColor: 'hsl(222.2 84% 5%)', border: '1px solid hsl(217.2 32.6% 17.5%)', borderRadius: 4 }}
          labelFormatter={() => ''}
          formatter={(v: number) => [v.toFixed(2), '']}
        />
        <Line type="monotone" dataKey="v" stroke="hsl(142 71% 45%)" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── Per-agent summary row ──────────────────────────────────────────────────────

interface AgentRow {
  agent: Agent
  summary: EvaluationSummary | null
  loading: boolean
}

function AgentRow({ agent, summary, loading }: AgentRow) {
  if (loading) return (
    <tr className="border-b border-border/50">
      <td colSpan={5} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td>
    </tr>
  )

  const score = summary?.avg_score
  const ratio = summary ? summary.thumbs_up_ratio : null

  return (
    <tr className="border-b border-border/50 hover:bg-accent/20 transition-colors">
      <td className="px-4 py-3">
        <div>
          <p className="text-sm font-medium">{agent.name}</p>
          <p className="text-xs text-muted-foreground font-mono">{agent.id.slice(0, 8)}…</p>
        </div>
      </td>
      <td className="px-4 py-3 text-center">
        {score != null ? (
          <div className="flex flex-col items-center gap-0.5">
            <span className="text-sm font-bold tabular-nums text-amber-400">{score.toFixed(2)}</span>
            <Stars score={score} />
          </div>
        ) : <span className="text-xs text-muted-foreground">—</span>}
      </td>
      <td className="px-4 py-3 text-center">
        {ratio != null
          ? <span className={`text-sm font-mono ${ratio >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>{(ratio * 100).toFixed(0)}%</span>
          : <span className="text-xs text-muted-foreground">—</span>}
      </td>
      <td className="px-4 py-3 text-center">
        <span className="text-sm tabular-nums">{summary?.total_evaluations ?? 0}</span>
      </td>
      <td className="px-4 py-3">
        {summary && summary.trend_7d.length > 0
          ? <Sparkline data={summary.trend_7d} />
          : <span className="text-xs text-muted-foreground">—</span>}
      </td>
    </tr>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function EvaluationsPage() {
  const qc = useQueryClient()
  const [anomalySeverity, setAnomalySeverity] = useState<'' | 'high' | 'medium' | 'low'>('')
  const [anomalyType, setAnomalyType] = useState('')

  const { data: agents = [], isLoading: agentsLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: listAgents,
    staleTime: 60_000,
  })

  // Fetch all agents' summaries in parallel
  const summaryQueries = useQueries({
    queries: agents.map(a => ({
      queryKey: ['eval-summary', a.id],
      queryFn: () => getEvaluationSummary(a.id),
      staleTime: 60_000,
      retry: false,
    })),
  })

  // Fetch all agents' open anomalies in parallel
  const anomalyQueries = useQueries({
    queries: agents.map(a => ({
      queryKey: ['anomalies', a.id, false],
      queryFn: () => listAnomalies(a.id, false),
      staleTime: 30_000,
      retry: false,
    })),
  })

  // Fetch all agents' active A/B tests in parallel
  const abTestQueries = useQueries({
    queries: agents.map(a => ({
      queryKey: ['ab-tests', a.id],
      queryFn: () => listABTests(a.id),
      staleTime: 30_000,
      retry: false,
    })),
  })

  const resolveMut = useMutation({
    mutationFn: ({ agentId, anomalyId }: { agentId: string; anomalyId: string }) =>
      resolveAnomaly(agentId, anomalyId),
    onSuccess: (_, vars) => {
      toast.success('Anomaly resolved')
      void qc.invalidateQueries({ queryKey: ['anomalies', vars.agentId] })
    },
    onError: () => toast.error('Failed to resolve anomaly'),
  })

  // Aggregated metrics
  const { bestAgent, worstAgent, globalAvg, totalAnomalies } = useMemo(() => {
    const withScore = agents
      .map((a, i) => ({ agent: a, score: summaryQueries[i]?.data?.avg_score ?? null }))
      .filter(x => x.score != null) as { agent: Agent; score: number }[]

    const sorted = [...withScore].sort((a, b) => b.score - a.score)
    const best = sorted[0] ?? null
    const worst = sorted[sorted.length - 1] ?? null
    const allScores = withScore.map(x => x.score)
    const avg = allScores.length > 0 ? allScores.reduce((a, b) => a + b, 0) / allScores.length : null

    const totalAnom = anomalyQueries.reduce((acc, q) => acc + (q.data?.count ?? 0), 0)

    return { bestAgent: best, worstAgent: worst, globalAvg: avg, totalAnomalies: totalAnom }
  }, [agents, summaryQueries, anomalyQueries])

  // Agent table sorted by score desc
  const sortedAgents = useMemo(() => {
    return agents
      .map((a, i) => ({
        agent: a,
        summary: summaryQueries[i]?.data ?? null,
        loading: summaryQueries[i]?.isLoading ?? true,
      }))
      .sort((a, b) => {
        const sa = a.summary?.avg_score ?? -1
        const sb = b.summary?.avg_score ?? -1
        return sb - sa
      })
  }, [agents, summaryQueries])

  // Global anomalies flattened
  const allAnomalies = useMemo(() => {
    return agents.flatMap((a, i) =>
      (anomalyQueries[i]?.data?.items ?? []).map(anm => ({ ...anm, agentName: a.name, agentId: a.id }))
    ).sort((a, b) => {
      const sev = { high: 3, medium: 2, low: 1 }
      return (sev[b.severity] ?? 0) - (sev[a.severity] ?? 0)
    })
  }, [agents, anomalyQueries])

  // Anomaly filter
  const allAnomalyTypes = useMemo(() => {
    const s = new Set<string>()
    allAnomalies.forEach(a => s.add(String(a.anomaly_type)))
    return [...s].sort()
  }, [allAnomalies])

  const filteredAnomalies = useMemo(() => {
    return allAnomalies.filter(a => {
      if (anomalySeverity && a.severity !== anomalySeverity) return false
      if (anomalyType && String(a.anomaly_type) !== anomalyType) return false
      return true
    })
  }, [allAnomalies, anomalySeverity, anomalyType])

  // Active A/B tests across all agents
  const activeABTests = useMemo(() => {
    return agents.flatMap((a, i) =>
      (abTestQueries[i]?.data?.items ?? [])
        .filter(t => t.status === 'active')
        .map(t => ({ ...t, agentName: a.name }))
    )
  }, [agents, abTestQueries])

  const summariesLoading = agentsLoading || summaryQueries.some(q => q.isLoading)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-5 border-b border-border shrink-0">
        <h1 className="text-xl font-semibold tracking-tight">Evaluations</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Ratings, scores, and anomalies across all agents</p>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-8">
          {/* Global summary cards */}
          {summariesLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[0,1,2,3].map(i => <Skeleton key={i} className="h-24" />)}
            </div>
          ) : agents.length === 0 ? (
            <EmptyState icon={BarChart3} title="No agents" description="Create an agent to start tracking evaluations." />
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Global Avg Score</p>
                  {globalAvg != null ? (
                    <>
                      <div className="text-2xl font-bold tabular-nums text-amber-400">{globalAvg.toFixed(2)}</div>
                      <Stars score={globalAvg} />
                    </>
                  ) : <span className="text-muted-foreground text-sm">No data</span>}
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Best Agent</p>
                  {bestAgent ? (
                    <>
                      <div className="text-sm font-semibold truncate mt-1">{bestAgent.agent.name}</div>
                      <div className="flex items-center gap-1 mt-0.5">
                        <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                        <span className="text-xs text-emerald-400 font-mono">{bestAgent.score.toFixed(2)}</span>
                      </div>
                    </>
                  ) : <span className="text-muted-foreground text-sm">—</span>}
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Worst Agent</p>
                  {worstAgent && worstAgent.agent.id !== bestAgent?.agent.id ? (
                    <>
                      <div className="text-sm font-semibold truncate mt-1">{worstAgent.agent.name}</div>
                      <div className="flex items-center gap-1 mt-0.5">
                        <TrendingDown className="h-3.5 w-3.5 text-red-400" />
                        <span className="text-xs text-red-400 font-mono">{worstAgent.score.toFixed(2)}</span>
                      </div>
                    </>
                  ) : <span className="text-muted-foreground text-sm">—</span>}
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Unresolved Anomalies</p>
                  <div className={`text-2xl font-bold tabular-nums mt-1 ${totalAnomalies > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {totalAnomalies}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Agent table */}
          {agents.length > 0 && (
            <div>
              <h2 className="text-base font-semibold mb-3">Agents by Score</h2>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 border-b border-border">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Agent</th>
                      <th className="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Avg Score</th>
                      <th className="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">👍 Rate</th>
                      <th className="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Evals</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">7d Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedAgents.map(row => (
                      <AgentRow key={row.agent.id} {...row} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Active A/B tests */}
          {activeABTests.length > 0 && (
            <div>
              <h2 className="text-base font-semibold mb-3">Active A/B Tests</h2>
              <div className="space-y-2">
                {activeABTests.map(test => (
                  <Card key={test.id}>
                    <CardContent className="p-4 flex items-center gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{test.name}</span>
                          <Badge variant="warning" className="text-xs">active</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {test.agentName} · Split {Math.round(test.traffic_split * 100)}% A / {Math.round((1 - test.traffic_split) * 100)}% B
                        </p>
                        <div className="h-1.5 rounded-full overflow-hidden bg-muted flex mt-2 w-48">
                          <div className="h-full bg-sky-500" style={{ width: `${test.traffic_split * 100}%` }} />
                          <div className="h-full bg-violet-500 flex-1" />
                        </div>
                      </div>
                      <Badge variant="secondary">{formatRelativeTime(test.started_at)}</Badge>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* Global anomalies */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold">Unresolved Anomalies</h2>
              <div className="flex items-center gap-2">
                <select
                  value={anomalySeverity}
                  onChange={e => setAnomalySeverity(e.target.value as '' | 'high' | 'medium' | 'low')}
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="">All severities</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
                {allAnomalyTypes.length > 0 && (
                  <select
                    value={anomalyType}
                    onChange={e => setAnomalyType(e.target.value)}
                    className="h-8 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="">All types</option>
                    {allAnomalyTypes.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                )}
              </div>
            </div>

            {anomalyQueries.some(q => q.isLoading) ? (
              <div className="space-y-2">{[0,1,2].map(i => <Skeleton key={i} className="h-16" />)}</div>
            ) : filteredAnomalies.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                {allAnomalies.length === 0 ? 'No unresolved anomalies' : 'No anomalies match the filters'}
              </div>
            ) : (
              <div className="space-y-2">
                {filteredAnomalies.map(a => (
                  <Card key={a.id}>
                    <CardContent className="flex items-center gap-4 p-4">
                      <AlertTriangle className={`h-5 w-5 shrink-0 ${a.severity === 'high' ? 'text-red-400' : a.severity === 'medium' ? 'text-amber-400' : 'text-muted-foreground'}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium">{String(a.anomaly_type)}</span>
                          <Badge variant={SEVERITY_VARIANT[a.severity] ?? 'secondary'} className="text-xs">{a.severity}</Badge>
                          <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{a.agentName}</span>
                        </div>
                        {Object.keys(a.details ?? {}).length > 0 && (
                          <p className="text-xs text-muted-foreground mt-0.5 truncate">
                            {Object.entries(a.details).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                          </p>
                        )}
                        <p className="text-xs text-muted-foreground">{formatRelativeTime(a.created_at)}</p>
                      </div>
                      <Button
                        size="sm" variant="outline" className="h-7 text-xs shrink-0"
                        onClick={() => resolveMut.mutate({ agentId: a.agentId, anomalyId: a.id })}
                        disabled={resolveMut.isPending}
                      >
                        <X className="h-3 w-3 mr-1" />Resolve
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
