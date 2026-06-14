import { getClient } from './client'
import type { Agent, AgentList, AgentStatusHistoryEntry, AgentStatusResponse, TagCount } from '@/types/api'

export async function listAgents(params?: {
  status?: string
  tags?: string
}): Promise<AgentList> {
  const { data } = await getClient().get<AgentList>('/v1/agents', { params })
  return data
}

export async function getAgent(agentId: string): Promise<Agent> {
  const { data } = await getClient().get<Agent>(`/v1/agents/${agentId}`)
  return data
}

export async function getAgentStatus(agentId: string): Promise<AgentStatusResponse> {
  const { data } = await getClient().get<AgentStatusResponse>(
    `/v1/agents/${agentId}/status`,
  )
  return data
}

export async function createAgent(body: {
  name: string
  description?: string
  tags?: string[]
  config?: Record<string, unknown>
}): Promise<Agent> {
  const { data } = await getClient().post<Agent>('/v1/agents', body)
  return data
}

export async function updateAgent(
  agentId: string,
  body: {
    name?: string
    description?: string
    tags?: string[]
    config?: Record<string, unknown>
  },
): Promise<Agent> {
  const { data } = await getClient().patch<Agent>(`/v1/agents/${agentId}`, body)
  return data
}

export async function deleteAgent(agentId: string): Promise<void> {
  await getClient().delete(`/v1/agents/${agentId}`)
}

export async function listAgentTags(): Promise<TagCount[]> {
  const { data } = await getClient().get<TagCount[]>('/v1/agents/tags')
  return data
}

export async function addAgentTags(agentId: string, tags: string[]): Promise<Agent> {
  const { data } = await getClient().post<Agent>(`/v1/agents/${agentId}/tags`, { tags })
  return data
}

export async function removeAgentTag(agentId: string, tag: string): Promise<Agent> {
  const { data } = await getClient().delete<Agent>(
    `/v1/agents/${agentId}/tags/${encodeURIComponent(tag)}`,
  )
  return data
}

export async function getAgentStatusHistory(
  agentId: string,
  limit = 10,
): Promise<AgentStatusHistoryEntry[]> {
  const { data } = await getClient().get<AgentStatusHistoryEntry[]>(
    `/v1/agents/${agentId}/status/history`,
    { params: { limit } },
  )
  return data
}
