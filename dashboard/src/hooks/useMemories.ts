import { useQuery } from '@tanstack/react-query'
import { listMemories } from '@/api/memory'

export function useMemories(agentId: string, includeArchived = false) {
  return useQuery({
    queryKey: ['memories', agentId, includeArchived],
    queryFn: () => listMemories(agentId, { include_archived: includeArchived }),
    enabled: !!agentId,
  })
}
