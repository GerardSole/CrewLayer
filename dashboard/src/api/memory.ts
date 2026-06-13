import { getClient } from './client'
import type { Memory, MemoryListResponse, MemoryStatsResponse, RecallResponse, ShortMemoryResponse } from '@/types/api'

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
  minSimilarity = 0.0,
): Promise<RecallResponse> {
  const { data } = await getClient().post<RecallResponse>(
    `/v1/agents/${agentId}/memory/recall`,
    { query, limit, min_similarity: minSimilarity },
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
  tags?: string[],
): Promise<Memory> {
  const { data } = await getClient().post<Memory>(`/v1/agents/${agentId}/memory`, {
    content,
    importance,
    tags,
  })
  return data
}

export async function getShortMemory(
  agentId: string,
  sessionId = 'default',
  limit = 50,
): Promise<ShortMemoryResponse> {
  const { data } = await getClient().get<ShortMemoryResponse>(
    `/v1/agents/${agentId}/memory/messages`,
    { params: { session_id: sessionId, limit } },
  )
  return data
}

export async function appendMessage(
  agentId: string,
  sessionId: string,
  role: string,
  content: string,
): Promise<void> {
  await getClient().post(
    `/v1/agents/${agentId}/memory/messages`,
    { role, content },
    { params: { session_id: sessionId } },
  )
}

export async function extractMemories(
  agentId: string,
  conversation: string,
  sessionId?: string,
): Promise<{ extracted_count: number; memory_ids: string[] }> {
  const { data } = await getClient().post(
    `/v1/agents/${agentId}/memory/extract`,
    { conversation, session_id: sessionId },
  )
  return data as { extracted_count: number; memory_ids: string[] }
}
