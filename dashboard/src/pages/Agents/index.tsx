import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, Plus, RefreshCw, Bot, ChevronRight, X } from 'lucide-react'
import { toast } from 'sonner'

import { listAgentTags } from '@/api/agents'
import { useAgents, useCreateAgent } from '@/hooks/useAgents'
import { Sheet } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'
import type { Agent, AgentStatus } from '@/types/api'

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

// ── New Agent Form ─────────────────────────────────────────────────────────────

function NewAgentForm({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [configText, setConfigText] = useState('{}')
  const [configError, setConfigError] = useState('')
  const createAgent = useCreateAgent()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    let config: Record<string, unknown> = {}
    try {
      config = JSON.parse(configText)
    } catch {
      setConfigError('Invalid JSON')
      return
    }
    setConfigError('')

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    createAgent.mutate(
      { name: name.trim(), description: description.trim() || undefined, tags, config },
      {
        onSuccess: () => {
          toast.success(`Agent "${name}" created`)
          onClose()
        },
        onError: () => toast.error('Failed to create agent'),
      },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-1.5">
        <label className="text-sm font-medium">Name *</label>
        <Input
          placeholder="my-agent"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoFocus
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">Description</label>
        <Input
          placeholder="What does this agent do?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">Tags</label>
        <Input
          placeholder="production, sales (comma-separated)"
          value={tagsInput}
          onChange={(e) => setTagsInput(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">Separate multiple tags with commas</p>
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">Config (JSON)</label>
        <Textarea
          placeholder="{}"
          value={configText}
          onChange={(e) => {
            setConfigText(e.target.value)
            setConfigError('')
          }}
          rows={5}
          className={configError ? 'border-destructive' : ''}
        />
        {configError && <p className="text-xs text-destructive">{configError}</p>}
      </div>

      <div className="flex gap-2 pt-2">
        <Button type="submit" disabled={!name.trim() || createAgent.isPending} className="flex-1">
          {createAgent.isPending ? 'Creating…' : 'Create Agent'}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── Tag filter dropdown ────────────────────────────────────────────────────────

function TagFilter({
  allTags,
  selected,
  onChange,
}: {
  allTags: string[]
  selected: string[]
  onChange: (tags: string[]) => void
}) {
  const [open, setOpen] = useState(false)

  if (allTags.length === 0) return null

  return (
    <div className="relative">
      <Button
        variant={selected.length > 0 ? 'secondary' : 'outline'}
        size="sm"
        onClick={() => setOpen(!open)}
      >
        Tags
        {selected.length > 0 && (
          <span className="ml-1.5 rounded-full bg-primary/20 px-1.5 py-0.5 text-xs">
            {selected.length}
          </span>
        )}
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-48 rounded-lg border border-border bg-background shadow-xl">
            <div className="p-1">
              {allTags.map((tag) => (
                <label
                  key={tag}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm hover:bg-accent"
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
                    className="rounded accent-primary"
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

// ── Agent row ─────────────────────────────────────────────────────────────────

function AgentRow({ agent, onClick }: { agent: Agent; onClick: () => void }) {
  return (
    <tr
      className="border-b border-border hover:bg-accent/30 cursor-pointer transition-colors group"
      onClick={onClick}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <Bot className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <p className="font-medium text-sm truncate">{agent.name}</p>
            {agent.description && (
              <p className="text-xs text-muted-foreground truncate max-w-xs">
                {agent.description}
              </p>
            )}
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[agent.status]}`} />
          <Badge variant={STATUS_VARIANT[agent.status]} className="capitalize text-xs">
            {agent.status}
          </Badge>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1 max-w-xs">
          {agent.tags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              {t}
            </span>
          ))}
          {agent.tags.length > 3 && (
            <span className="text-xs text-muted-foreground">+{agent.tags.length - 3}</span>
          )}
          {agent.tags.length === 0 && (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-sm">
        {agent.current_session_id ? (
          <Badge variant="info" className="text-xs">Active</Badge>
        ) : (
          <span className="text-muted-foreground text-xs">None</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
        {formatRelativeTime(agent.status_updated_at)}
      </td>
      <td className="px-4 py-3">
        <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
      </td>
    </tr>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

const STATUS_FILTERS: Array<{ label: string; value: AgentStatus | '' }> = [
  { label: 'All', value: '' },
  { label: 'Idle', value: 'idle' },
  { label: 'Working', value: 'working' },
  { label: 'Error', value: 'error' },
]

export default function AgentsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<AgentStatus | ''>('')
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)

  const { data: allAgents = [], isLoading, refetch } = useAgents()

  const { data: tagCounts = [] } = useQuery({
    queryKey: ['agent-tags'],
    queryFn: listAgentTags,
    staleTime: 60_000,
  })

  const allTags = tagCounts.map((t) => t.tag)

  const filtered = useMemo(() => {
    return allAgents.filter((a) => {
      const matchName =
        search === '' || a.name.toLowerCase().includes(search.toLowerCase())
      const matchStatus = statusFilter === '' || a.status === statusFilter
      const matchTags =
        tagFilter.length === 0 || tagFilter.some((t) => a.tags.includes(t))
      return matchName && matchStatus && matchTags
    })
  }, [allAgents, search, statusFilter, tagFilter])

  const hasFilters = search !== '' || statusFilter !== '' || tagFilter.length > 0
  const clearFilters = () => {
    setSearch('')
    setStatusFilter('')
    setTagFilter([])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-5 border-b border-border shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agents</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {allAgents.length} agent{allAgents.length !== 1 ? 's' : ''} in this tenant
          </p>
        </div>
        <Button size="sm" onClick={() => setDrawerOpen(true)}>
          <Plus className="h-4 w-4" />
          New Agent
        </Button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 px-6 py-3 border-b border-border shrink-0">
        <div className="relative w-60">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-8 text-sm"
          />
        </div>

        <div className="flex gap-1">
          {STATUS_FILTERS.map(({ label, value }) => (
            <Button
              key={value}
              variant={statusFilter === value ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 text-xs"
              onClick={() => setStatusFilter(value)}
            >
              {label}
            </Button>
          ))}
        </div>

        <TagFilter allTags={allTags} selected={tagFilter} onChange={setTagFilter} />

        {hasFilters && (
          <Button variant="ghost" size="sm" className="h-8 text-xs gap-1" onClick={clearFilters}>
            <X className="h-3 w-3" />
            Clear
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="ml-auto h-8 w-8"
          onClick={() => void refetch()}
          title="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="space-y-2 p-6">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-lg" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Bot}
            title={hasFilters ? 'No agents match your filters' : 'No agents yet'}
            description={
              hasFilters
                ? 'Try different filters or clear them.'
                : 'Create your first agent with the New Agent button.'
            }
            action={
              hasFilters ? (
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-background/95 backdrop-blur">
              <tr className="border-b border-border text-left">
                <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Agent
                </th>
                <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Status
                </th>
                <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Tags
                </th>
                <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Session
                </th>
                <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Last Activity
                </th>
                <th className="px-4 py-3 w-8" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((agent) => (
                <AgentRow
                  key={agent.id}
                  agent={agent}
                  onClick={() => navigate(`/agents/${agent.id}`)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* New Agent Drawer */}
      <Sheet
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="New Agent"
        description="Create a new agent for this tenant"
      >
        <NewAgentForm onClose={() => setDrawerOpen(false)} />
      </Sheet>
    </div>
  )
}
