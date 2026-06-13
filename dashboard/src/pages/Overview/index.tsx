import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  Zap,
  Activity,
  BarChart2,
  AlertTriangle,
  Star,
  TrendingUp,
  TrendingDown,
  Minus,
} from 'lucide-react'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { differenceInHours, format, subHours } from 'date-fns'

import { listAgents } from '@/api/agents'
import { getUsage } from '@/api/usage'
import { listAuditLog } from '@/api/audit'
import { listAnomalies, getEvaluationSummary } from '@/api/evaluations'
import { useAllAgentStats } from '@/hooks/useAgents'
import { useQueries } from '@tanstack/react-query'
import { getActionStats } from '@/api/actions'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatNumber, formatRelativeTime } from '@/lib/formatters'
import type { AuditEntry } from '@/types/api'

const REFETCH = 30_000

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
    labelStyle: { color: 'hsl(210 40% 98%)' },
  },
} as const

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({
  title,
  value,
  icon: Icon,
  iconColor = 'text-muted-foreground',
  sub,
  trend,
  loading,
}: {
  title: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  iconColor?: string
  sub?: { text: string; direction?: 'up' | 'down' | 'neutral' }
  trend?: 'up' | 'down' | 'neutral'
  loading?: boolean
}) {
  const TrendIcon =
    trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus

  return (
    <Card className="relative overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className={`h-4 w-4 ${iconColor}`} />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-28 mb-1" />
        ) : (
          <div className="text-2xl font-bold tabular-nums">{value}</div>
        )}
        {sub && (
          <div
            className={`mt-1 flex items-center gap-1 text-xs ${
              sub.direction === 'up'
                ? 'text-emerald-400'
                : sub.direction === 'down'
                ? 'text-red-400'
                : 'text-muted-foreground'
            }`}
          >
            {sub.direction && (
              <TrendIcon className="h-3 w-3" />
            )}
            {sub.text}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Activity row ──────────────────────────────────────────────────────────────

const METHOD_COLOR: Record<string, string> = {
  GET: 'text-blue-400',
  POST: 'text-emerald-400',
  PATCH: 'text-amber-400',
  PUT: 'text-amber-400',
  DELETE: 'text-red-400',
}

function ActivityRow({ entry }: { entry: AuditEntry }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-border/40 last:border-0 min-w-0">
      <span
        className={`font-mono text-xs font-semibold w-12 shrink-0 ${
          METHOD_COLOR[entry.method] ?? 'text-foreground'
        }`}
      >
        {entry.method}
      </span>
      <span className="text-xs text-muted-foreground font-mono truncate flex-1 min-w-0">
        {entry.path}
      </span>
      <Badge
        variant={
          entry.status_code < 300
            ? 'success'
            : entry.status_code < 500
            ? 'warning'
            : 'error'
        }
        className="text-xs shrink-0"
      >
        {entry.status_code}
      </Badge>
      <span className="text-xs text-muted-foreground shrink-0 whitespace-nowrap">
        {formatRelativeTime(entry.timestamp)}
      </span>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function OverviewPage() {
  const { data: allAgents = [], isLoading: agentsLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => listAgents(),
    refetchInterval: REFETCH,
  })

  const { data: workingAgents = [] } = useQuery({
    queryKey: ['agents', { status: 'working' }],
    queryFn: () => listAgents({ status: 'working' }),
    refetchInterval: REFETCH,
  })

  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
    refetchInterval: REFETCH,
  })

  const { data: auditLog, isLoading: auditLoading } = useQuery({
    queryKey: ['audit-log', 'overview'],
    queryFn: () => listAuditLog({ limit: 200 }),
    refetchInterval: REFETCH,
  })

  // Stats for all agents (parallel)
  const agentStatQueries = useAllAgentStats(allAgents.map((a) => a.id))

  // Anomalies for error-state agents
  const errorAgents = allAgents.filter((a) => a.status === 'error')
  const anomalyQueries = useQueries({
    queries: errorAgents.map((agent) => ({
      queryKey: ['anomalies', agent.id, false],
      queryFn: () => listAnomalies(agent.id, false),
      staleTime: REFETCH,
      retry: false,
    })),
  })

  // Eval summaries for first 6 agents
  const evalSampleAgents = allAgents.slice(0, 6)
  const evalQueries = useQueries({
    queries: evalSampleAgents.map((agent) => ({
      queryKey: ['eval-summary', agent.id],
      queryFn: () => getEvaluationSummary(agent.id),
      staleTime: REFETCH,
      retry: false,
    })),
  })

  // ── Derived ────────────────────────────────────────────────────────────────

  const { totalActions, avgErrorRate, top5Tools, statsReady } = useMemo(() => {
    let total = 0
    let weightedErr = 0
    let totalWeight = 0
    const toolMap: Record<string, number> = {}

    agentStatQueries.forEach((q) => {
      if (!q.data) return
      total += q.data.total_actions
      weightedErr += q.data.error_rate * q.data.total_actions
      totalWeight += q.data.total_actions
      q.data.by_tool?.forEach((t) => {
        if (!t) return
        toolMap[t.tool_name] = (toolMap[t.tool_name] ?? 0) + (t.count ?? 0)
      })
    })

    const avgErrorRate = totalWeight > 0 ? weightedErr / totalWeight : 0
    const top5Tools = Object.entries(toolMap)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([name, count]) => ({ name, count }))

    return {
      totalActions: total,
      avgErrorRate,
      top5Tools,
      statsReady: agentStatQueries.length > 0 && agentStatQueries.every((q) => !q.isLoading),
    }
  }, [agentStatQueries])

  const avgScore = useMemo(() => {
    const scores = evalQueries
      .map((q) => q.data?.avg_score)
      .filter((s): s is number => s != null && s > 0)
    if (scores.length === 0) return null
    return scores.reduce((a, b) => a + b, 0) / scores.length
  }, [evalQueries])

  // Hourly chart data from audit log (last 24h)
  const hourlyData = useMemo(() => {
    const now = new Date()
    const hours = Array.from({ length: 24 }, (_, i) => ({
      hour: format(subHours(now, 23 - i), 'HH:mm'),
      requests: 0,
    }))
    auditLog?.items.forEach((entry) => {
      const diff = differenceInHours(now, new Date(entry.timestamp))
      if (diff >= 0 && diff < 24) {
        hours[23 - diff].requests++
      }
    })
    return hours
  }, [auditLog])

  // All active anomalies sorted by severity
  const activeAnomalies = useMemo(() => {
    const SEV = { high: 0, medium: 1, low: 2 }
    return anomalyQueries
      .flatMap((q) => q.data?.items ?? [])
      .sort((a, b) => (SEV[a.severity] ?? 2) - (SEV[b.severity] ?? 2))
  }, [anomalyQueries])

  const statsLoading = allAgents.length > 0 && !statsReady

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
        <p className="text-sm text-muted-foreground">Tenant health at a glance</p>
      </div>

      {/* ── KPI row ── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          title="Total Agents"
          value={agentsLoading ? '—' : allAgents.length}
          icon={Bot}
          iconColor="text-blue-400"
          loading={agentsLoading}
          sub={{ text: `${allAgents.filter((a) => a.status === 'idle').length} idle` }}
        />
        <KpiCard
          title="Active Now"
          value={agentsLoading ? '—' : workingAgents.length}
          icon={Zap}
          iconColor="text-emerald-400"
          loading={agentsLoading}
          trend={workingAgents.length > 0 ? 'up' : 'neutral'}
          sub={{
            text: `${errorAgents.length} in error`,
            direction: errorAgents.length > 0 ? 'down' : 'neutral',
          }}
        />
        <KpiCard
          title="Requests Today"
          value={usageLoading ? '—' : formatNumber(usage?.usage.requests_today ?? 0)}
          icon={Activity}
          iconColor="text-violet-400"
          loading={usageLoading}
          sub={{ text: `${usage?.usage.requests_this_minute ?? 0}/min now` }}
        />
        <KpiCard
          title="Total Actions"
          value={statsLoading ? '—' : formatNumber(totalActions)}
          icon={BarChart2}
          iconColor="text-amber-400"
          loading={statsLoading}
          sub={{ text: `${allAgents.length} agent${allAgents.length !== 1 ? 's' : ''} tracked` }}
        />
        <KpiCard
          title="Error Rate"
          value={
            statsLoading
              ? '—'
              : `${(avgErrorRate * 100).toFixed(1)}%`
          }
          icon={AlertTriangle}
          iconColor={avgErrorRate > 0.1 ? 'text-red-400' : 'text-muted-foreground'}
          loading={statsLoading}
          trend={avgErrorRate > 0.1 ? 'down' : 'up'}
          sub={{
            text: avgErrorRate > 0.1 ? 'Above 10% threshold' : 'Within limits',
            direction: avgErrorRate > 0.1 ? 'down' : 'up',
          }}
        />
        <KpiCard
          title="Avg Eval Score"
          value={avgScore == null ? '—' : avgScore.toFixed(2)}
          icon={Star}
          iconColor="text-yellow-400"
          sub={{
            text:
              avgScore != null
                ? `${evalSampleAgents.length} agents sampled`
                : 'No evaluations yet',
          }}
        />
      </div>

      {/* ── Charts ── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">API Activity — last 24 h</CardTitle>
          </CardHeader>
          <CardContent>
            {auditLoading ? (
              <Skeleton className="h-48 w-full rounded-md" />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={hourlyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                  <XAxis
                    dataKey="hour"
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                    interval={3}
                  />
                  <YAxis
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip {...CHART.tooltip} />
                  <Line
                    type="monotone"
                    dataKey="requests"
                    stroke="hsl(217.2 91.2% 59.8%)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: 'hsl(217.2 91.2% 59.8%)' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Top 5 Tools by Usage</CardTitle>
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-48 w-full rounded-md" />
            ) : top5Tools.length === 0 ? (
              <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
                No actions recorded yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={top5Tools} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
                  <XAxis
                    type="number"
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                    width={90}
                  />
                  <Tooltip {...CHART.tooltip} />
                  <Bar
                    dataKey="count"
                    fill="hsl(142 71% 45%)"
                    radius={[0, 4, 4, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Activity feed + Anomalies ── */}
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Recent Activity</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {auditLoading ? (
              <div className="space-y-3">
                {[...Array(6)].map((_, i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : (auditLog?.items.length ?? 0) === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No activity yet
              </p>
            ) : (
              <div className="max-h-80 overflow-y-auto pr-1">
                {auditLog!.items.slice(0, 20).map((entry) => (
                  <ActivityRow key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Active Anomalies</CardTitle>
              {activeAnomalies.length > 0 && (
                <Badge variant="error">{activeAnomalies.length}</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {activeAnomalies.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-10">
                <div className="rounded-full bg-emerald-500/10 p-3">
                  <Zap className="h-5 w-5 text-emerald-400" />
                </div>
                <p className="text-sm text-muted-foreground">All clear</p>
              </div>
            ) : (
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {activeAnomalies.slice(0, 10).map((anomaly) => {
                  const agent = allAgents.find((a) => a.id === anomaly.agent_id)
                  return (
                    <div
                      key={anomaly.id}
                      className="flex items-start gap-3 rounded-lg border border-border p-3"
                    >
                      <AlertTriangle
                        className={`h-4 w-4 shrink-0 mt-0.5 ${
                          anomaly.severity === 'high'
                            ? 'text-red-400'
                            : anomaly.severity === 'medium'
                            ? 'text-amber-400'
                            : 'text-muted-foreground'
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="text-xs font-medium truncate">
                            {anomaly.anomaly_type}
                          </span>
                          <Badge
                            variant={
                              anomaly.severity === 'high'
                                ? 'error'
                                : anomaly.severity === 'medium'
                                ? 'warning'
                                : 'secondary'
                            }
                            className="text-xs shrink-0"
                          >
                            {anomaly.severity}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground truncate">
                          {agent?.name ?? 'Unknown'} ·{' '}
                          {formatRelativeTime(anomaly.created_at)}
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
