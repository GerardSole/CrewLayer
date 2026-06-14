import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query'
import {
  listAgents,
  getAgent,
  createAgent,
  updateAgent,
  deleteAgent,
  getAgentStatus,
  getAgentStatusHistory,
  listAgentTags,
} from '@/api/agents'
import { getActionStats } from '@/api/actions'
import { getEvaluationSummary } from '@/api/evaluations'

export function useAgents(params?: { status?: string; tags?: string }) {
  return useQuery({
    queryKey: ['agents', params],
    queryFn: () => listAgents(params),
    refetchInterval: 2_000,
  })
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => getAgent(agentId),
    enabled: !!agentId,
  })
}

export function useAgentStatus(agentId: string, refetchInterval = 1_000) {
  return useQuery({
    queryKey: ['agent-status', agentId],
    queryFn: () => getAgentStatus(agentId),
    enabled: !!agentId,
    refetchInterval,
  })
}

export function useAgentStatusHistory(agentId: string) {
  return useQuery({
    queryKey: ['agent-status-history', agentId],
    queryFn: () => getAgentStatusHistory(agentId, 10),
    enabled: !!agentId,
    refetchInterval: 3_000,
  })
}

export function useAgentTags() {
  return useQuery({
    queryKey: ['agent-tags'],
    queryFn: listAgentTags,
    staleTime: 60_000,
  })
}

export function useAgentStats(agentId: string) {
  return useQuery({
    queryKey: ['agent-stats', agentId],
    queryFn: () => getActionStats(agentId),
    enabled: !!agentId,
    staleTime: 30_000,
    retry: false,
  })
}

export function useAgentEvalSummary(agentId: string) {
  return useQuery({
    queryKey: ['eval-summary', agentId],
    queryFn: () => getEvaluationSummary(agentId),
    enabled: !!agentId,
    staleTime: 30_000,
    retry: false,
  })
}

export function useAllAgentStats(agentIds: string[]) {
  return useQueries({
    queries: agentIds.map((id) => ({
      queryKey: ['agent-stats', id],
      queryFn: () => getActionStats(id),
      staleTime: 30_000,
      retry: false,
    })),
  })
}

export function useAllEvalSummaries(agentIds: string[]) {
  return useQueries({
    queries: agentIds.map((id) => ({
      queryKey: ['eval-summary', id],
      queryFn: () => getEvaluationSummary(id),
      staleTime: 30_000,
      retry: false,
    })),
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createAgent,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['agents'] })
      void qc.invalidateQueries({ queryKey: ['agent-tags'] })
    },
  })
}

export function useUpdateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      body,
    }: {
      agentId: string
      body: Parameters<typeof updateAgent>[1]
    }) => updateAgent(agentId, body),
    onSuccess: (data, { agentId }) => {
      void qc.invalidateQueries({ queryKey: ['agents'] })
      void qc.invalidateQueries({ queryKey: ['agent-tags'] })
      qc.setQueryData(['agent', agentId], data)
    },
  })
}

export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAgent,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}
