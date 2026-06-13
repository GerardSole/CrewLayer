import { useQuery } from '@tanstack/react-query'
import { Bot, Brain, Activity, Users } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { getUsage } from '@/api/usage'
import { listAgents } from '@/api/agents'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatNumber, formatRelativeTime } from '@/lib/formatters'
import type { AgentStatus } from '@/types/api'

const STATUS_VARIANT: Record<AgentStatus, 'success' | 'warning' | 'error'> = {
  idle: 'success',
  working: 'warning',
  error: 'error',
}

const CHART_STYLE = {
  grid: 'hsl(217.2 32.6% 17.5%)',
  tick: { fontSize: 11, fill: 'hsl(215 20.2% 55%)' },
  tooltip: {
    contentStyle: {
      backgroundColor: 'hsl(222.2 74% 7%)',
      border: '1px solid hsl(217.2 32.6% 17.5%)',
      borderRadius: '6px',
      fontSize: 12,
    },
    labelStyle: { color: 'hsl(210 40% 98%)' },
  },
}

const mockTrend = Array.from({ length: 14 }, (_, i) => ({
  day: new Date(Date.now() - (13 - i) * 86_400_000).toLocaleDateString('en', {
    month: 'short',
    day: 'numeric',
  }),
  requests: Math.floor(Math.random() * 200 + 30),
  embeddings: Math.floor(Math.random() * 30 + 5),
}))

function StatCard({
  title,
  value,
  icon: Icon,
  sub,
  loading,
}: {
  title: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  sub?: string
  loading?: boolean
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <div className="text-2xl font-bold">{value}</div>
        )}
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export default function OverviewPage() {
  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
    refetchInterval: 60_000,
  })

  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ['agents', { limit: 6 }],
    queryFn: () => listAgents(),
  })

  const requestsToday = usage?.usage.requests_today ?? 0
  const limitPerDay = usage?.limits.per_day
  const agentCount = agents?.length ?? 0

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
        <p className="text-sm text-muted-foreground">Your CrewLayer instance at a glance</p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Agents"
          value={agentsLoading ? '—' : formatNumber(agentCount)}
          icon={Bot}
          loading={agentsLoading}
        />
        <StatCard
          title="Requests Today"
          value={usageLoading ? '—' : formatNumber(requestsToday)}
          icon={Activity}
          sub={limitPerDay ? `of ${formatNumber(limitPerDay)} limit` : undefined}
          loading={usageLoading}
        />
        <StatCard
          title="Req / min"
          value={usageLoading ? '—' : formatNumber(usage?.usage.requests_this_minute ?? 0)}
          icon={Users}
          sub={usage?.limits.per_minute ? `limit ${usage.limits.per_minute}/min` : undefined}
          loading={usageLoading}
        />
        <StatCard
          title="Embeddings / min"
          value={usageLoading ? '—' : formatNumber(usage?.usage.embedding_requests_this_minute ?? 0)}
          icon={Brain}
          sub={usage?.limits.embedding_per_minute ? `limit ${usage.limits.embedding_per_minute}/min` : undefined}
          loading={usageLoading}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">API Requests — last 14 days</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={mockTrend}>
                <defs>
                  <linearGradient id="gReq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(217.2 91.2% 59.8%)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="hsl(217.2 91.2% 59.8%)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLE.grid} />
                <XAxis dataKey="day" tick={CHART_STYLE.tick} tickLine={false} axisLine={false} />
                <YAxis tick={CHART_STYLE.tick} tickLine={false} axisLine={false} />
                <Tooltip {...CHART_STYLE.tooltip} />
                <Area
                  type="monotone"
                  dataKey="requests"
                  stroke="hsl(217.2 91.2% 59.8%)"
                  fill="url(#gReq)"
                  strokeWidth={2}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Embedding Requests — last 14 days</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={mockTrend}>
                <defs>
                  <linearGradient id="gEmb" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(142 71% 45%)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="hsl(142 71% 45%)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLE.grid} />
                <XAxis dataKey="day" tick={CHART_STYLE.tick} tickLine={false} axisLine={false} />
                <YAxis tick={CHART_STYLE.tick} tickLine={false} axisLine={false} />
                <Tooltip {...CHART_STYLE.tooltip} />
                <Area
                  type="monotone"
                  dataKey="embeddings"
                  stroke="hsl(142 71% 45%)"
                  fill="url(#gEmb)"
                  strokeWidth={2}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Recent agents */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Recent Agents</CardTitle>
        </CardHeader>
        <CardContent>
          {agentsLoading ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : (agents?.length ?? 0) === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No agents yet. Create one with the CLI or SDK.
            </p>
          ) : (
            <div className="space-y-2">
              {agents?.slice(0, 6).map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2.5"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <Bot className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{agent.name}</p>
                      <p className="truncate text-xs text-muted-foreground font-mono">
                        {agent.id.slice(0, 8)}… · {formatRelativeTime(agent.status_updated_at)}
                      </p>
                    </div>
                  </div>
                  <Badge variant={STATUS_VARIANT[agent.status]} className="ml-3 shrink-0 capitalize">
                    {agent.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
