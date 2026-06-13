import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LogOut, Circle } from 'lucide-react'
import { getUsage } from '@/api/usage'
import { getClient } from '@/api/client'
import { clearCredentials, getBaseURL } from '@/api/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function Header() {
  const navigate = useNavigate()
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)

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

  const planVariant =
    plan === 'pro' ? 'info' : plan === 'enterprise' ? 'default' : 'secondary'

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur">
      <div className="flex items-center gap-3 min-w-0">
        <span className="truncate text-sm font-medium text-muted-foreground">{baseURL}</span>
        <Badge variant={planVariant as 'default' | 'secondary' | 'info'} className="capitalize shrink-0">
          {plan}
        </Badge>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <Circle
            className={cn(
              'h-2 w-2 fill-current',
              apiOnline === true && 'text-emerald-400',
              apiOnline === false && 'text-red-400',
              apiOnline === null && 'text-muted-foreground',
            )}
          />
          <span
            className={cn(
              'text-xs',
              apiOnline === true && 'text-emerald-400',
              apiOnline === false && 'text-red-400',
              apiOnline === null && 'text-muted-foreground',
            )}
          >
            {apiOnline === true ? 'API online' : apiOnline === false ? 'API offline' : 'Checking…'}
          </span>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => {
            clearCredentials()
            navigate('/login')
          }}
          title="Disconnect"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
