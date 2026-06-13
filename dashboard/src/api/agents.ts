import { getClient } from './client'
import type { Agent, AgentList } from '@/types/api'

export async function listAgents(params?: {
  status?: string
  tags?: string
  limit?: number
}): Promise<AgentList> {
  const { data } = await getClient().get<AgentList>('/v1/agents', { params })
  return data
}

export async function getAgent(agentId: string): Promise<Agent> {
  const { data } = await getClient().get<Agent>(`/v1/agents/${agentId}`)
  return data
}

export async function createAgent(body: {
  name: string
  description?: string
  tags?: string[]
}): Promise<Agent> {
  const { data } = await getClient().post<Agent>('/v1/agents', body)
  return data
}

export async function updateAgent(
  agentId: string,
  body: { name?: string; description?: string; tags?: string[]; status?: string },
): Promise<Agent> {
  const { data } = await getClient().patch<Agent>(`/v1/agents/${agentId}`, body)
  return data
}

export async function deleteAgent(agentId: string): Promise<void> {
  await getClient().delete(`/v1/agents/${agentId}`)
}
