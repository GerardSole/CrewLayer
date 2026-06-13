import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LogOut, Circle, Menu, Search } from 'lucide-react'
import { getUsage } from '@/api/usage'
import { getClient } from '@/api/client'
import { clearCredentials, getBaseURL } from '@/api/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useSidebar } from './Layout'

export function Header() {
  const navigate = useNavigate()
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const { setMobileOpen } = useSidebar()

  const { data: usage } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
    refetchInterval: 60_000,
    retry: false,
  })

  useEffect(() => {
    const check = async () => {
      try {
        await getClient().get('/health')
        setApiOnline(true)
      } catch {
        setApiOnline(false)
      }
    }
    void check()
    const id = setInterval(() => void check(), 30_000)
    return () => clearInterval(id)
  }, [])

  const plan = usage?.plan ?? 'free'
  const baseURL = getBaseURL()
  const planVariant = plan === 'pro' ? 'success' : plan === 'enterprise' ? 'info' : 'secondary'

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur gap-3">
      {/* Hamburger (mobile only) */}
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 lg:hidden shrink-0"
        onClick={() => setMobileOpen(true)}
      >
        <Menu className="h-4 w-4" />
      </Button>

      {/* Instance info */}
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="hidden sm:block truncate text-sm font-medium text-muted-foreground">{baseURL}</span>
        <Badge variant={planVariant as 'default' | 'secondary' | 'success' | 'info'} className="capitalize shrink-0 hidden sm:inline-flex">
          {plan}
        </Badge>
      </div>

      <div className="flex items-center gap-2">
        {/* Cmd+K hint */}
        <button
          type="button"
          onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))}
          className="hidden md:flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/70 transition-colors"
        >
          <Search className="h-3 w-3" />
          <span>Search</span>
          <kbd className="ml-1 rounded border border-border px-1 py-0.5 text-[10px]">⌘K</kbd>
        </button>

        {/* API status */}
        <div className="flex items-center gap-1.5">
          <Circle className={cn('h-2 w-2 fill-current', apiOnline === true && 'text-emerald-400', apiOnline === false && 'text-red-400', apiOnline === null && 'text-muted-foreground')} />
          <span className={cn('text-xs hidden sm:block', apiOnline === true && 'text-emerald-400', apiOnline === false && 'text-red-400', apiOnline === null && 'text-muted-foreground')}>
            {apiOnline === true ? 'Online' : apiOnline === false ? 'Offline' : '…'}
          </span>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => { clearCredentials(); navigate('/login') }}
          title="Disconnect"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
