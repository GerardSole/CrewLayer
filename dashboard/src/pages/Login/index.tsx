import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layers, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { validateApiKey, storeCredentials } from '@/api/auth'
import { DEFAULT_BASE_URL } from '@/lib/constants'

export default function LoginPage() {
  const navigate = useNavigate()
  const [baseURL, setBaseURL] = useState(DEFAULT_BASE_URL)
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!apiKey.trim()) {
      setError('API key is required')
      return
    }
    setLoading(true)
    try {
      const url = baseURL.trim().replace(/\/$/, '')
      const valid = await validateApiKey(url, apiKey.trim())
      if (!valid) {
        setError('Invalid API key or server unreachable. Check the URL and key and try again.')
        return
      }
      storeCredentials(url, apiKey.trim())
      toast.success('Connected to CrewLayer')
      navigate('/overview')
    } catch {
      setError('Could not connect. Make sure CrewLayer is running at the URL above.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
            <Layers className="h-8 w-8 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">CrewLayer</h1>
            <p className="text-sm text-muted-foreground">Open source AI agent backend</p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Connect to your instance</CardTitle>
            <CardDescription>
              Enter your CrewLayer URL and API key to access the dashboard.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(e) => void handleConnect(e)} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="url">Instance URL</Label>
                <Input
                  id="url"
                  type="url"
                  placeholder="http://localhost:8000"
                  value={baseURL}
                  onChange={(e) => setBaseURL(e.target.value)}
                  disabled={loading}
                  autoComplete="off"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="apikey">API Key</Label>
                <div className="relative">
                  <Input
                    id="apikey"
                    type={showKey ? 'text' : 'password'}
                    placeholder="crwl_…"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    disabled={loading}
                    className="pr-10"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-red-400">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Connecting…' : 'Connect'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="mt-4 text-center text-xs text-muted-foreground">
          Don&apos;t have an instance?{' '}
          <a
            href="https://github.com/GerardSole/CrewLayer"
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            Get started →
          </a>
        </p>
      </div>
    </div>
  )
}
