import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard, Bot, Brain, Activity, BarChart3, FileText,
  Share2, Webhook, ClipboardList, Settings, Search, ArrowRight,
} from 'lucide-react'
import { listAgents } from '@/api/agents'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

interface Item {
  id: string
  label: string
  description?: string
  icon: React.ComponentType<{ className?: string }>
  action: () => void
}

const PAGES: Omit<Item, 'action'>[] = [
  { id: 'overview', label: 'Overview', description: 'Dashboard overview', icon: LayoutDashboard },
  { id: 'agents', label: 'Agents', description: 'Manage agents', icon: Bot },
  { id: 'memory', label: 'Memory', description: 'Memory explorer', icon: Brain },
  { id: 'actions', label: 'Actions', description: 'Action history', icon: Activity },
  { id: 'evaluations', label: 'Evaluations', description: 'Scores & anomalies', icon: BarChart3 },
  { id: 'prompts', label: 'Prompts', description: 'Prompt versions', icon: FileText },
  { id: 'blackboard', label: 'Blackboard', description: 'Shared context', icon: Share2 },
  { id: 'webhooks', label: 'Webhooks', description: 'HTTP callbacks', icon: Webhook },
  { id: 'audit', label: 'Audit Log', description: 'API activity', icon: ClipboardList },
  { id: 'settings', label: 'Settings', description: 'Keys & config', icon: Settings },
]

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: listAgents,
    staleTime: 60_000,
    enabled: open,
  })

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(p => !p)
        setQuery('')
        setActiveIdx(0)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50)
  }, [open])

  const items: Item[] = useMemo(() => {
    const pages: Item[] = PAGES.map(p => ({
      ...p,
      action: () => { navigate(`/${p.id}`); setOpen(false) },
    }))
    const agentItems: Item[] = agents.map(a => ({
      id: `agent-${a.id}`,
      label: a.name,
      description: `Agent · ${a.id.slice(0, 8)}…`,
      icon: Bot,
      action: () => { navigate(`/agents/${a.id}`); setOpen(false) },
    }))
    return [...pages, ...agentItems]
  }, [agents, navigate])

  const filtered = useMemo(() => {
    if (!query.trim()) return items.slice(0, 8)
    const q = query.toLowerCase()
    return items.filter(i => i.label.toLowerCase().includes(q) || i.description?.toLowerCase().includes(q)).slice(0, 10)
  }, [items, query])

  useEffect(() => { setActiveIdx(0) }, [filtered])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, filtered.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && filtered[activeIdx]) { filtered[activeIdx].action() }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="p-0 overflow-hidden max-w-lg gap-0">
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, agents…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
            ESC
          </kbd>
        </div>

        <div className="py-2 max-h-80 overflow-y-auto">
          {filtered.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">No results for "{query}"</p>
          ) : (
            filtered.map((item, i) => {
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  type="button"
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={item.action}
                  className={cn(
                    'w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors',
                    i === activeIdx ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50',
                  )}
                >
                  <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md border', i === activeIdx ? 'border-primary/30 bg-primary/10' : 'border-border bg-muted/30')}>
                    <Icon className={cn('h-3.5 w-3.5', i === activeIdx ? 'text-primary' : 'text-muted-foreground')} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{item.label}</p>
                    {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
                  </div>
                  {i === activeIdx && <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                </button>
              )
            })
          )}
        </div>

        <div className="border-t border-border px-4 py-2 flex items-center gap-3 text-[10px] text-muted-foreground">
          <span>↑↓ navigate</span>
          <span>↵ open</span>
          <span className="ml-auto">⌘K to close</span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
