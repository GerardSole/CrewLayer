import { getClient } from './client'
import type { Memory, MemoryListResponse, MemoryStatsResponse, RecallResponse } from '@/types/api'

export async function listMemories(
  agentId: string,
  params?: { include_archived?: boolean; page?: number; page_size?: number },
): Promise<MemoryListResponse> {
  const { data } = await getClient().get<MemoryListResponse>(
    `/v1/agents/${agentId}/memory`,
    { params },
  )
  return data
}

export async function recallMemories(
  agentId: string,
  query: string,
  limit = 10,
): Promise<RecallResponse> {
  const { data } = await getClient().post<RecallResponse>(
    `/v1/agents/${agentId}/memory/recall`,
    { query, limit },
  )
  return data
}

export async function deleteMemory(agentId: string, memoryId: string): Promise<void> {
  await getClient().delete(`/v1/agents/${agentId}/memory/${memoryId}`)
}

export async function getMemoryStats(agentId: string): Promise<MemoryStatsResponse> {
  const { data } = await getClient().get<MemoryStatsResponse>(
    `/v1/agents/${agentId}/memories/stats`,
  )
  return data
}

export async function appendMemory(
  agentId: string,
  content: string,
  importance?: number,
): Promise<Memory> {
  const { data } = await getClient().post<Memory>(`/v1/agents/${agentId}/memory`, {
    content,
    importance,
  })
  return data
}
