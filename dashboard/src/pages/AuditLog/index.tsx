import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardList, RefreshCw, Download, ChevronRight, X } from 'lucide-react'
import { listAuditLog } from '@/api/audit'
import { Sheet } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { formatDateTime } from '@/lib/formatters'
import type { AuditEntry } from '@/types/api'

function statusVariant(code: number): 'success' | 'error' | 'warning' | 'secondary' {
  if (code < 300) return 'success'
  if (code < 400) return 'secondary'
  if (code < 500) return 'warning'
  return 'error'
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-zinc-500/10 text-zinc-300 border-zinc-500/20',
  POST: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  PATCH: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  PUT: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  DELETE: 'bg-red-500/10 text-red-400 border-red-500/20',
}

const RESOURCE_TYPES = ['agent', 'memory', 'action', 'session', 'episode', 'webhook', 'api_key', 'context', 'prompt']

function exportCSV(entries: AuditEntry[]) {
  const header = ['timestamp', 'actor', 'method', 'path', 'resource_type', 'resource_id', 'status_code', 'ip_address']
  const rows = entries.map(e => [
    e.timestamp,
    e.actor_key_name,
    e.method,
    e.path,
    e.resource_type ?? '',
    e.resource_id ?? '',
    String(e.status_code),
    e.ip_address ?? '',
  ])
  const csv = [header, ...rows].map(r => r.map(v => `"${v.replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit-log-${new Date().toISOString().split('T')[0]}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function AuditLogPage() {
  const [resourceType, setResourceType] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null)
  const [extraItems, setExtraItems] = useState<AuditEntry[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  const params = useMemo(() => ({
    resource_type: resourceType || undefined,
    from: fromDate ? new Date(fromDate).toISOString() : undefined,
    to: toDate ? new Date(toDate + 'T23:59:59').toISOString() : undefined,
    limit: 100,
  }), [resourceType, fromDate, toDate])

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['audit-log', params],
    queryFn: () => listAuditLog(params),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const allItems = [...(data?.items ?? []), ...extraItems]
  const hasFilters = !!resourceType || !!fromDate || !!toDate

  const clearFilters = () => { setResourceType(''); setFromDate(''); setToDate('') }

  async function loadMore() {
    if (!nextCursor) return
    setLoadingMore(true)
    try {
      const res = await listAuditLog({ ...params, cursor: nextCursor })
      setExtraItems(prev => [...prev, ...res.items])
      setNextCursor(res.next_cursor ?? null)
    } finally {
      setLoadingMore(false)
    }
  }

  // reset extra on filter change
  useMemo(() => { setExtraItems([]); setNextCursor(data?.next_cursor ?? null) }, [data?.items[0]?.id])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-start justify-between px-6 py-5 border-b border-border shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Audit Log</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            All API activity · {allItems.length} entries shown
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => exportCSV(allItems)} disabled={allItems.length === 0}>
            <Download className="h-3.5 w-3.5" />CSV
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => void refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <Input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="h-8 text-xs w-36" placeholder="From" />
            <span className="text-xs text-muted-foreground">–</span>
            <Input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="h-8 text-xs w-36" placeholder="To" />
            <div className="h-4 border-l border-border mx-1" />
            {['', ...RESOURCE_TYPES].map(rt => (
              <button
                key={rt || 'all'}
                type="button"
                onClick={() => setResourceType(rt)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${resourceType === rt ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/50'}`}
              >
                {rt || 'All'}
              </button>
            ))}
            {hasFilters && (
              <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={clearFilters}>
                <X className="h-3 w-3" />Clear
              </Button>
            )}
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="space-y-1.5">{[0,1,2,3,4,5].map(i => <Skeleton key={i} className="h-11" />)}</div>
          ) : allItems.length === 0 ? (
            <EmptyState icon={ClipboardList} title="No audit entries" description={hasFilters ? 'No entries match the selected filters.' : 'API activity will appear here.'} action={hasFilters ? <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button> : undefined} />
          ) : (
            <>
              <div className="rounded-lg border border-border overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 border-b border-border">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap">Timestamp</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Method</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Path</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Status</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Resource</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Actor</th>
                        <th className="px-3 py-2 w-8" />
                      </tr>
                    </thead>
                    <tbody>
                      {allItems.map(entry => (
                        <tr
                          key={entry.id}
                          className="border-b border-border/50 hover:bg-accent/20 cursor-pointer transition-colors group"
                          onClick={() => setSelectedEntry(entry)}
                        >
                          <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">{formatDateTime(entry.timestamp)}</td>
                          <td className="px-3 py-2.5">
                            <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold font-mono ${METHOD_COLORS[entry.method] ?? 'text-foreground border-border'}`}>
                              {entry.method}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground max-w-xs truncate">{entry.path}</td>
                          <td className="px-3 py-2.5">
                            <Badge variant={statusVariant(entry.status_code)} className="text-xs">{entry.status_code}</Badge>
                          </td>
                          <td className="px-3 py-2.5 text-xs text-muted-foreground">
                            {entry.resource_type
                              ? <><span className="text-foreground/80">{entry.resource_type}</span>{entry.resource_id && <span className="ml-1 font-mono opacity-60">{entry.resource_id.slice(0, 6)}…</span>}</>
                              : '—'}
                          </td>
                          <td className="px-3 py-2.5 text-xs text-muted-foreground">{entry.actor_key_name ?? '—'}</td>
                          <td className="px-3 py-2.5">
                            <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {(data?.next_cursor || nextCursor) && (
                <div className="flex justify-center">
                  <Button variant="outline" size="sm" onClick={() => void loadMore()} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : 'Load more'}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Detail sheet */}
      <Sheet
        open={!!selectedEntry}
        onClose={() => setSelectedEntry(null)}
        title={selectedEntry ? `${selectedEntry.method} ${selectedEntry.path}` : ''}
        description={selectedEntry ? formatDateTime(selectedEntry.timestamp) : undefined}
      >
        {selectedEntry && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Status</p>
                <Badge variant={statusVariant(selectedEntry.status_code)}>{selectedEntry.status_code}</Badge>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Actor</p>
                <p className="text-sm font-medium">{selectedEntry.actor_key_name ?? '—'}</p>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">IP Address</p>
                <code className="text-xs">{selectedEntry.ip_address ?? '—'}</code>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">API Key ID</p>
                <code className="text-xs font-mono">{selectedEntry.api_key_id ? selectedEntry.api_key_id.slice(0, 12) + '…' : '—'}</code>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Full Path</p>
              <code className="text-xs font-mono break-all text-foreground/90">{selectedEntry.path}</code>
            </div>
            {selectedEntry.resource_type && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Resource</p>
                <p className="text-sm"><span className="font-medium">{selectedEntry.resource_type}</span>{selectedEntry.resource_id && <code className="ml-2 text-xs text-muted-foreground">{selectedEntry.resource_id}</code>}</p>
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  )
}
