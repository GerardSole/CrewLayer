import { useQuery } from '@tanstack/react-query'
import { listActions, getActionStats } from '@/api/actions'

export function useActions(agentId: string, params?: { status?: string; limit?: number }) {
  return useQuery({
    queryKey: ['actions', agentId, params],
    queryFn: () => listActions(agentId, params),
    enabled: !!agentId,
  })
}

export function useActionStats(agentId: string) {
  return useQuery({
    queryKey: ['action-stats', agentId],
    queryFn: () => getActionStats(agentId),
    enabled: !!agentId,
  })
}
