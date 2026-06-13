import { useQuery } from '@tanstack/react-query'
import { listAgents, getAgent } from '@/api/agents'

export function useAgents(params?: { status?: string }) {
  return useQuery({
    queryKey: ['agents', params],
    queryFn: () => listAgents(params),
  })
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => getAgent(agentId),
    enabled: !!agentId,
  })
}
