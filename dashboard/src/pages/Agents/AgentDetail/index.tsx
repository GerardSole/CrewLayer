import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Pencil,
  Trash2,
  Plus,
  X,
  BarChart2,
  Star,
  AlertTriangle,
  Clock,
  Zap,
  BarChart,
  FileText,
  ListChecks,
} from 'lucide-react'
import { MemoryTab } from './MemoryTab'
import { ActionsTab } from './ActionsTab'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart as ReBarChart,
  Bar,
} from 'recharts'
import { subDays, format, differenceInDays } from 'date-fns'
import { toast } from 'sonner'

import { getAgent, updateAgent, deleteAgent, removeAgentTag, addAgentTags } from '@/api/agents'
import { getActionStats, listActions } from '@/api/actions'
import { getEvaluationSummary, listAnomalies } from '@/api/evaluations'
import { useAgentStatus, useUpdateAgent, useDeleteAgent } from '@/hooks/useAgents'
import { Sheet } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatNumber, formatRelativeTime, formatDuration } from '@/lib/formatters'
import type { AgentStatus } from '@/types/api'

// ── Constants ──────────────────────────────────────────────────────────────────

const STATUS_VARIANT: Record<AgentStatus, 'success' | 'warning' | 'error'> = {
  idle: 'success',
  working: 'warning',
  error: 'error',
}

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: 'bg-emerald-400',
  working: 'bg-amber-400 animate-pulse',
  error: 'bg-red-400',
}

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

// ── Edit Drawer ────────────────────────────────────────────────────────────────

function EditAgentDrawer({
  agentId,
  initialName,
  initialDescription,
  initialConfig,
  open,
  onClose,
}: {
  agentId: string
  initialName: string
  initialDescription?: string
  initialConfig?: Record<string, unknown>
  open: boolean
  onClose: () => void
}) {
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription ?? '')
  const [configText, setConfigText] = useState(
    JSON.stringify(initialConfig ?? {}, null, 2),
  )
  const [configError, setConfigError] = useState('')
  const updateMut = useUpdateAgent()

  useEffect(() => {
    if (open) {
      setName(initialName)
      setDescription(initialDescription ?? '')
      setConfigText(JSON.stringify(initialConfig ?? {}, null, 2))
      setConfigError('')
    }
  }, [open, initialName, initialDescription, initialConfig])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    let config: Record<string, unknown> = {}
    try {
      config = JSON.parse(configText)
    } catch {
      setConfigError('Invalid JSON')
      return
    }
    updateMut.mutate(
      {
        agentId,
        body: {
          name: name.trim(),
          description: description.trim() || undefined,
          config,
        },
      },
      {
        onSuccess: () => {
          toast.success('Agent updated')
          onClose()
        },
        onError: () => toast.error('Failed to update agent'),
      },
    )
  }

  return (
    <Sheet open={open} onClose={onClose} title="Edit Agent">
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Name *</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Description</label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Config (JSON)</label>
          <Textarea
            value={configText}
            onChange={(e) => {
              setConfigText(e.target.value)
              setConfigError('')
            }}
            rows={8}
            className={configError ? 'border-destructive' : ''}
          />
          {configError && <p className="text-xs text-destructive">{configError}</p>}
        </div>
        <div className="flex gap-2 pt-2">
          <Button type="submit" disabled={!name.trim() || updateMut.isPending} className="flex-1">
            {updateMut.isPending ? 'Saving…' : 'Save Changes'}
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Sheet>
  )
}

// ── Tag editor ─────────────────────────────────────────────────────────────────

function TagEditor({ agentId, tags }: { agentId: string; tags: string[] }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [tagInput, setTagInput] = useState('')

  const removeMut = useMutation({
    mutationFn: (tag: string) => removeAgentTag(agentId, tag),
    onSuccess: (data) => {
      qc.setQueryData(['agent', agentId], data)
      void qc.invalidateQueries({ queryKey: ['agents'] })
    },
    onError: () => toast.error('Failed to remove tag'),
  })

  const addMut = useMutation({
    mutationFn: (newTags: string[]) => addAgentTags(agentId, newTags),
    onSuccess: (data) => {
      qc.setQueryData(['agent', agentId], data)
      void qc.invalidateQueries({ queryKey: ['agents'] })
      setTagInput('')
      setAdding(false)
    },
    onError: () => toast.error('Failed to add tag'),
  })

  const handleAdd = () => {
    const t = tagInput.trim()
    if (!t || tags.includes(t)) return
    addMut.mutate([t])
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground"
        >
          {tag}
          <button
            type="button"
            onClick={() => removeMut.mutate(tag)}
            className="hover:text-foreground transition-colors"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      {adding ? (
        <div className="flex items-center gap-1">
          <Input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleAdd()
              }
              if (e.key === 'Escape') {
                setAdding(false)
                setTagInput('')
              }
            }}
            placeholder="tag name"
            className="h-7 w-28 text-xs"
            autoFocus
          />
          <Button
            type="button"
            size="sm"
            className="h-7 text-xs"
            onClick={handleAdd}
            disabled={addMut.isPending}
          >
            Add
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => { setAdding(false); setTagInput('') }}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-xs text-muted-foreground hover:border-primary hover:text-foreground transition-colors"
        >
          <Plus className="h-3 w-3" />
          Add tag
        </button>
      )}
    </div>
  )
}

// ── Mini stat card ─────────────────────────────────────────────────────────────

function MiniStat({
  label,
  value,
  icon: Icon,
  iconColor = 'text-muted-foreground',
  loading,
}: {
  label: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  iconColor?: string
  loading?: boolean
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-2">
          <Icon className={`h-4 w-4 ${iconColor}`} />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
        {loading ? (
          <Skeleton className="h-7 w-20" />
        ) : (
          <div className="text-xl font-bold tabular-nums">{value}</div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function AgentOverviewTab({ agentId }: { agentId: string }) {
  const since30d = useMemo(
    () => subDays(new Date(), 30).toISOString(),
    [],
  )

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['agent-stats', agentId],
    queryFn: () => getActionStats(agentId),
    staleTime: 30_000,
    retry: false,
  })

  const { data: evalSummary } = useQuery({
    queryKey: ['eval-summary', agentId],
    queryFn: () => getEvaluationSummary(agentId),
    staleTime: 30_000,
    retry: false,
  })

  const { data: anomalies } = useQuery({
    queryKey: ['anomalies', agentId, false],
    queryFn: () => listAnomalies(agentId, false),
    staleTime: 30_000,
    retry: false,
  })

  const { data: recentActions } = useQuery({
    queryKey: ['agent-actions-30d', agentId],
    queryFn: () => listActions(agentId, { since: since30d, limit: 500 }),
    staleTime: 60_000,
    retry: false,
  })

  // Group actions by day
  const dailyData = useMemo(() => {
    const now = new Date()
    const days = Array.from({ length: 30 }, (_, i) => ({
      day: format(subDays(now, 29 - i), 'MMM d'),
      actions: 0,
      errors: 0,
    }))
    recentActions?.items.forEach((a) => {
      const diff = differenceInDays(now, new Date(a.timestamp))
      if (diff >= 0 && diff < 30) {
        days[29 - diff].actions++
        if (a.status === 'error' || a.status === 'timeout') {
          days[29 - diff].errors++
        }
      }
    })
    return days
  }, [recentActions])

  const activeAnomalies = anomalies?.items ?? []

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MiniStat
          label="Total Actions"
          value={statsLoading ? '—' : formatNumber(stats?.total_actions ?? 0)}
          icon={ListChecks}
          iconColor="text-blue-400"
          loading={statsLoading}
        />
        <MiniStat
          label="Error Rate"
          value={
            statsLoading
              ? '—'
              : `${((stats?.error_rate ?? 0) * 100).toFixed(1)}%`
          }
          icon={AlertTriangle}
          iconColor={
            (stats?.error_rate ?? 0) > 0.1 ? 'text-red-400' : 'text-muted-foreground'
          }
          loading={statsLoading}
        />
        <MiniStat
          label="Avg Eval Score"
          value={
            evalSummary?.avg_score != null
              ? evalSummary.avg_score.toFixed(2)
              : '—'
          }
          icon={Star}
          iconColor="text-yellow-400"
        />
        <MiniStat
          label="Open Anomalies"
          value={activeAnomalies.length}
          icon={AlertTriangle}
          iconColor={activeAnomalies.length > 0 ? 'text-red-400' : 'text-muted-foreground'}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Actions — last 30 days</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={180}>
              <ReBarChart data={dailyData}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis
                  dataKey="day"
                  tick={CHART.tick}
                  tickLine={false}
                  axisLine={false}
                  interval={4}
                />
                <YAxis
                  tick={CHART.tick}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip {...CHART.tooltip} />
                <Bar dataKey="actions" fill="hsl(217.2 91.2% 59.8%)" radius={[2, 2, 0, 0]} />
                <Bar dataKey="errors" fill="hsl(0 62.8% 50%)" radius={[2, 2, 0, 0]} />
              </ReBarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {evalSummary && evalSummary.trend_7d.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Eval Score — last 7 days</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={evalSummary.trend_7d}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                  <XAxis
                    dataKey="day"
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    tick={CHART.tick}
                    tickLine={false}
                    axisLine={false}
                    domain={[0, 1]}
                  />
                  <Tooltip {...CHART.tooltip} />
                  <Line
                    type="monotone"
                    dataKey="avg_score"
                    stroke="hsl(142 71% 45%)"
                    strokeWidth={2}
                    dot={{ r: 3, fill: 'hsl(142 71% 45%)' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Top tools */}
      {stats && stats.by_tool.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">By Tool</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {stats.by_tool
                .sort((a, b) => b.count - a.count)
                .slice(0, 5)
                .map((t) => {
                  const pct = stats.total_actions > 0
                    ? (t.count / stats.total_actions) * 100
                    : 0
                  return (
                    <div key={t.tool_name} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono">{t.tool_name}</span>
                        <span className="text-muted-foreground">
                          {formatNumber(t.count)} calls ·{' '}
                          {(t.error_rate * 100).toFixed(0)}% err
                          {t.avg_duration_ms != null && (
                            <> · {formatDuration(t.avg_duration_ms)}</>
                          )}
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent anomalies */}
      {activeAnomalies.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold">Open Anomalies</h3>
          <div className="space-y-2">
            {activeAnomalies.slice(0, 5).map((a) => (
              <Card key={a.id}>
                <CardContent className="flex items-center gap-4 p-4">
                  <AlertTriangle
                    className={`h-5 w-5 shrink-0 ${
                      a.severity === 'high'
                        ? 'text-red-400'
                        : a.severity === 'medium'
                        ? 'text-amber-400'
                        : 'text-muted-foreground'
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium">{a.anomaly_type}</span>
                      <Badge
                        variant={
                          a.severity === 'high'
                            ? 'error'
                            : a.severity === 'medium'
                            ? 'warning'
                            : 'secondary'
                        }
                        className="text-xs"
                      >
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
        </div>
      )}
    </div>
  )
}

// ── Stub tab ───────────────────────────────────────────────────────────────────

function StubTab({
  icon: Icon,
  title,
  prompt,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  prompt: string
}) {
  return (
    <EmptyState
      icon={Icon}
      title={title}
      description={`This section will be implemented in ${prompt}.`}
    />
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AgentDetailPage() {
  const { id: agentId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState('overview')
  const [editOpen, setEditOpen] = useState(false)

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', agentId!],
    queryFn: () => getAgent(agentId!),
    enabled: !!agentId,
  })

  // Poll status every 10s
  const { data: liveStatus } = useAgentStatus(agentId ?? '', 10_000)
  const deleteMut = useDeleteAgent()

  const currentStatus = (liveStatus?.status ?? agent?.status ?? 'idle') as AgentStatus

  const handleDelete = () => {
    if (!agentId) return
    if (!confirm(`Delete agent "${agent?.name}"? This cannot be undone.`)) return
    deleteMut.mutate(agentId, {
      onSuccess: () => {
        toast.success('Agent deleted')
        navigate('/agents')
      },
      onError: () => toast.error('Failed to delete agent'),
    })
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  }

  if (!agent) {
    return (
      <EmptyState
        icon={Zap}
        title="Agent not found"
        description="This agent may have been deleted."
        action={
          <Button variant="outline" onClick={() => navigate('/agents')}>
            Back to Agents
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ── */}
      <div className="border-b border-border px-6 py-5 shrink-0 space-y-4">
        <button
          type="button"
          onClick={() => navigate('/agents')}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Agents
        </button>

        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold truncate">{agent.name}</h1>
              <div className="flex items-center gap-2 shrink-0">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[currentStatus]}`}
                />
                <Badge variant={STATUS_VARIANT[currentStatus]} className="capitalize text-xs">
                  {currentStatus}
                </Badge>
              </div>
            </div>

            {agent.description && (
              <p className="text-sm text-muted-foreground">{agent.description}</p>
            )}

            <TagEditor agentId={agentId!} tags={agent.tags} />
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive hover:text-destructive hover:bg-destructive/10"
              onClick={handleDelete}
              disabled={deleteMut.isPending}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </Button>
          </div>
        </div>

        <p className="text-xs text-muted-foreground font-mono">
          {agent.id}
        </p>
      </div>

      {/* ── Tabs ── */}
      <Tabs value={tab} onValueChange={setTab} className="flex flex-col flex-1 min-h-0">
        <div className="px-6 shrink-0">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="memory">Memory</TabsTrigger>
            <TabsTrigger value="actions">Actions</TabsTrigger>
            <TabsTrigger value="evaluations">Evaluations</TabsTrigger>
            <TabsTrigger value="prompts">Prompts</TabsTrigger>
          </TabsList>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-6">
          <TabsContent value="overview">
            <AgentOverviewTab agentId={agentId!} />
          </TabsContent>
          <TabsContent value="memory">
            <MemoryTab agentId={agentId!} />
          </TabsContent>
          <TabsContent value="actions">
            <ActionsTab agentId={agentId!} />
          </TabsContent>
          <TabsContent value="evaluations">
            <StubTab icon={BarChart} title="Evaluations" prompt="Prompt 5" />
          </TabsContent>
          <TabsContent value="prompts">
            <StubTab icon={FileText} title="Prompts" prompt="Prompt 5" />
          </TabsContent>
        </div>
      </Tabs>

      {/* Edit drawer */}
      <EditAgentDrawer
        agentId={agentId!}
        initialName={agent.name}
        initialDescription={agent.description}
        initialConfig={agent.config}
        open={editOpen}
        onClose={() => setEditOpen(false)}
      />
    </div>
  )
}
