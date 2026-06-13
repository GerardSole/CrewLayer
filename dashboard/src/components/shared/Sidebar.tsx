import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Bot, Brain, Activity, BarChart3, FileText,
  Share2, Webhook, ClipboardList, Settings, ChevronLeft, ChevronRight, Layers,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'

const NAV = [
  { path: '/overview', label: 'Overview', icon: LayoutDashboard },
  { path: '/agents', label: 'Agents', icon: Bot },
  { path: '/memory', label: 'Memory', icon: Brain },
  { path: '/actions', label: 'Actions', icon: Activity },
  { path: '/evaluations', label: 'Evaluations', icon: BarChart3 },
  { path: '/prompts', label: 'Prompts', icon: FileText },
  { path: '/blackboard', label: 'Blackboard', icon: Share2 },
  { path: '/webhooks', label: 'Webhooks', icon: Webhook },
  { path: '/audit', label: 'Audit Log', icon: ClipboardList },
  { path: '/settings', label: 'Settings', icon: Settings },
] as const

export function Sidebar() {
  const { pathname } = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-bg))] transition-all duration-200',
        collapsed ? 'w-14' : 'w-60',
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          'flex h-14 items-center border-b border-[hsl(var(--sidebar-border))]',
          collapsed ? 'justify-center px-2' : 'gap-2.5 px-4',
        )}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <Layers className="h-4 w-4 text-primary" />
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold tracking-tight text-foreground">CrewLayer</span>
        )}
      </div>

      {/* Navigation */}
      <ScrollArea className="flex-1 py-2">
        <nav className="space-y-0.5 px-2">
          {NAV.map(({ path, label, icon: Icon }) => {
            const active = pathname === path || pathname.startsWith(path + '/')
            return (
              <Link
                key={path}
                to={path}
                title={collapsed ? label : undefined}
                className={cn(
                  'flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                  'hover:bg-accent hover:text-accent-foreground',
                  active ? 'bg-accent text-accent-foreground' : 'text-muted-foreground',
                  collapsed && 'justify-center gap-0 px-0',
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{label}</span>}
              </Link>
            )
          })}
        </nav>
      </ScrollArea>

      {/* Collapse toggle */}
      <div className="border-t border-[hsl(var(--sidebar-border))] p-2">
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            'w-full text-muted-foreground hover:text-foreground',
            collapsed ? 'justify-center px-0' : 'justify-start gap-2',
          )}
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="h-4 w-4" />
              <span className="text-xs">Collapse</span>
            </>
          )}
        </Button>
      </div>
    </aside>
  )
}
