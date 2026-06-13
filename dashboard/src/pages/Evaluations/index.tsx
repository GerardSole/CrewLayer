import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, ThumbsUp, ThumbsDown, AlertTriangle } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { listAgents } from '@/api/agents'
import { getEvaluationSummary, listAnomalies } from '@/api/evaluations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'

const SEVERITY_VARIANT: Record<string, 'error' | 'warning' | 'secondary'> = {
  high: 'error',
  medium: 'warning',
  low: 'secondary',
}

export default function EvaluationsPage() {
  const [agentId, setAgentId] = useState('')

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => listAgents(),
  })

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['eval-summary', agentId],
    queryFn: () => getEvaluationSummary(agentId),
    enabled: !!agentId,
  })

  const { data: anomalies, isLoading: anomalyLoading } = useQuery({
    queryKey: ['anomalies', agentId],
    queryFn: () => listAnomalies(agentId, false),
    enabled: !!agentId,
  })

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Evaluations</h1>
        <p className="text-sm text-muted-foreground">Ratings, trends, and anomaly detection</p>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">
          Select agent:
        </label>
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">— choose an agent —</option>
          {(agents ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      {agentId && (
        <>
          {summaryLoading ? (
            <div className="grid gap-4 sm:grid-cols-3">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}
            </div>
          ) : summary ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Card>
                  <CardContent className="p-4">
                    <p className="text-xs text-muted-foreground">Total Evaluations</p>
                    <p className="text-2xl font-bold">{summary.total_evaluations}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 flex items-center gap-3">
                    <ThumbsUp className="h-5 w-5 text-emerald-400" />
                    <div>
                      <p className="text-xs text-muted-foreground">Thumbs Up</p>
                      <p className="text-xl font-bold text-emerald-400">{summary.thumbs_up}</p>
                    </div>
                    <ThumbsDown className="h-5 w-5 text-red-400 ml-4" />
                    <div>
                      <p className="text-xs text-muted-foreground">Thumbs Down</p>
                      <p className="text-xl font-bold text-red-400">{summary.thumbs_down}</p>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <p className="text-xs text-muted-foreground">Positive Rate</p>
                    <p className={`text-2xl font-bold ${summary.thumbs_up_ratio >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {(summary.thumbs_up_ratio * 100).toFixed(0)}%
                    </p>
                  </CardContent>
                </Card>
              </div>

              {summary.trend_7d.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Trend — last 7 days</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={summary.trend_7d}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(217.2 32.6% 17.5%)" />
                        <XAxis
                          dataKey="day"
                          tick={{ fontSize: 11, fill: 'hsl(215 20.2% 55%)' }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          tick={{ fontSize: 11, fill: 'hsl(215 20.2% 55%)' }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(222.2 74% 7%)',
                            border: '1px solid hsl(217.2 32.6% 17.5%)',
                            borderRadius: '6px',
                            fontSize: 12,
                          }}
                        />
                        <Bar dataKey="thumbs_up" fill="hsl(142 71% 45%)" radius={[3, 3, 0, 0]} />
                        <Bar dataKey="thumbs_down" fill="hsl(0 62.8% 50%)" radius={[3, 3, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <EmptyState icon={BarChart3} title="No evaluations yet" description="Evaluations will appear once agents receive ratings." />
          )}

          {/* Anomalies */}
          <div>
            <h2 className="mb-3 text-base font-semibold">Open Anomalies</h2>
            {anomalyLoading ? (
              <div className="space-y-2">
                {[0, 1].map((i) => <Skeleton key={i} className="h-14" />)}
              </div>
            ) : (anomalies?.items.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">No unresolved anomalies.</p>
            ) : (
              <div className="space-y-2">
                {anomalies?.items.map((a) => (
                  <Card key={a.id}>
                    <CardContent className="flex items-center gap-4 p-4">
                      <AlertTriangle className={`h-5 w-5 shrink-0 ${a.severity === 'high' ? 'text-red-400' : a.severity === 'medium' ? 'text-amber-400' : 'text-muted-foreground'}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{a.anomaly_type}</span>
                          <Badge variant={SEVERITY_VARIANT[a.severity] ?? 'secondary'}>
                            {a.severity}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {formatRelativeTime(a.created_at)}
                        </p>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {!agentId && (
        <EmptyState icon={BarChart3} title="Select an agent" description="Choose an agent above to view evaluations." />
      )}
    </div>
  )
}
