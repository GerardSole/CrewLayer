import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Share2, Trash2, Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { listNamespaceKeys, writeContext, deleteContext } from '@/api/context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatRelativeTime } from '@/lib/formatters'

export default function BlackboardPage() {
  const qc = useQueryClient()
  const [namespace, setNamespace] = useState('default')
  const [nsInput, setNsInput] = useState('default')
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['context', namespace],
    queryFn: () => listNamespaceKeys(namespace),
  })

  const writeMut = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      writeContext(namespace, key, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      setNewKey('')
      setNewValue('')
      setShowAdd(false)
      toast.success('Context written')
    },
    onError: () => toast.error('Failed to write context'),
  })

  const deleteMut = useMutation({
    mutationFn: (key: string) => deleteContext(namespace, key),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['context', namespace] })
      toast.success('Key deleted')
    },
    onError: () => toast.error('Failed to delete key'),
  })

  const handleWrite = () => {
    if (!newKey.trim()) return
    let parsed: unknown = newValue
    try { parsed = JSON.parse(newValue) } catch { /* use raw string */ }
    writeMut.mutate({ key: newKey.trim(), value: parsed })
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Blackboard</h1>
        <p className="text-sm text-muted-foreground">Shared context storage across agents</p>
      </div>

      {/* Namespace picker */}
      <div className="flex items-center gap-2">
        <Input
          placeholder="Namespace"
          value={nsInput}
          onChange={(e) => setNsInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setNamespace(nsInput)}
          className="w-48"
        />
        <Button variant="secondary" size="sm" onClick={() => setNamespace(nsInput)}>
          Load
        </Button>
        <Button variant="ghost" size="icon" onClick={() => void refetch()}>
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setShowAdd(!showAdd)}
        >
          <Plus className="h-4 w-4" /> Add key
        </Button>
      </div>

      {/* Add form */}
      {showAdd && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <p className="text-sm font-medium">New entry in <code className="bg-muted px-1 rounded">{namespace}</code></p>
            <div className="flex gap-2">
              <Input
                placeholder="key"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                className="w-48"
              />
              <Input
                placeholder='value (string or JSON)'
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                className="flex-1"
              />
              <Button onClick={handleWrite} disabled={!newKey || writeMut.isPending}>
                Save
              </Button>
              <Button variant="ghost" onClick={() => setShowAdd(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Entries */}
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}
        </div>
      ) : (data?.entries.length ?? 0) === 0 ? (
        <EmptyState
          icon={Share2}
          title={`Namespace "${namespace}" is empty`}
          description="Add a key above or write context via the API."
        />
      ) : (
        <div className="space-y-2">
          {data?.entries.map((entry) => (
            <Card key={entry.id}>
              <CardContent className="flex items-start justify-between gap-4 p-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-sm font-semibold">{entry.key}</code>
                    <Badge variant="secondary" className="text-xs">v{entry.version}</Badge>
                    {entry.expires_at && (
                      <Badge variant="warning" className="text-xs">
                        expires {formatRelativeTime(entry.expires_at)}
                      </Badge>
                    )}
                  </div>
                  <pre className="text-xs text-muted-foreground overflow-auto max-h-20 whitespace-pre-wrap">
                    {JSON.stringify(entry.value, null, 2)}
                  </pre>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Updated {formatRelativeTime(entry.updated_at)}
                    {entry.written_by && ` by ${entry.written_by}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                  disabled={deleteMut.isPending}
                  onClick={() => {
                    if (confirm(`Delete key "${entry.key}"?`)) deleteMut.mutate(entry.key)
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
