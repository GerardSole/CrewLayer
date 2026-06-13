import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Settings, LogOut, Key, Database, Cpu } from 'lucide-react'
import { toast } from 'sonner'
import { getUsage } from '@/api/usage'
import { clearCredentials, getBaseURL } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { formatNumber } from '@/lib/formatters'
import { STORAGE_KEYS } from '@/lib/constants'

const PLAN_VARIANT: Record<string, 'success' | 'info' | 'default'> = {
  free: 'success',
  pro: 'info',
  enterprise: 'default',
}

function UsageBar({ used, limit, label }: { used: number; limit?: number; label: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0
  const color = pct > 90 ? 'bg-red-400' : pct > 70 ? 'bg-amber-400' : 'bg-primary'
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-muted-foreground">{label}</span>
        <span>{formatNumber(used)}{limit ? ` / ${formatNumber(limit)}` : ''}</span>
      </div>
      {limit && (
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const navigate = useNavigate()
  const baseURL = getBaseURL()
  const apiKey = localStorage.getItem(STORAGE_KEYS.API_KEY) ?? ''

  const { data: usage } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
  })

  const handleDisconnect = () => {
    clearCredentials()
    toast.success('Disconnected')
    navigate('/login')
  }

  return (
    <div className="space-y-6 p-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Connection info and usage overview</p>
      </div>

      {/* Connection */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            Connection
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-xs text-muted-foreground mb-1">Instance URL</p>
            <code className="text-sm">{baseURL}</code>
          </div>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground mb-1">API Key</p>
            <div className="flex items-center gap-2">
              <Key className="h-4 w-4 text-muted-foreground" />
              <code className="text-sm">{apiKey.slice(0, 8)}{'•'.repeat(Math.max(0, apiKey.length - 8))}</code>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Plan & usage */}
      {usage && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4" />
              Plan & Usage
              <Badge variant={PLAN_VARIANT[usage.plan]} className="ml-auto capitalize">
                {usage.plan}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <UsageBar
              used={usage.usage.requests_today}
              limit={usage.limits.per_day ?? undefined}
              label="API requests today"
            />
            <UsageBar
              used={usage.usage.requests_this_minute}
              limit={usage.limits.per_minute ?? undefined}
              label="API requests / min"
            />
            <UsageBar
              used={usage.usage.embedding_requests_this_minute}
              limit={usage.limits.embedding_per_minute ?? undefined}
              label="Embedding requests / min"
            />
          </CardContent>
        </Card>
      )}

      {/* Danger zone */}
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-destructive">
            <Settings className="h-4 w-4" />
            Danger zone
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Disconnect from instance</p>
              <p className="text-xs text-muted-foreground">
                Removes stored credentials from this browser.
              </p>
            </div>
            <Button variant="destructive" size="sm" onClick={handleDisconnect}>
              <LogOut className="h-4 w-4" />
              Disconnect
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
