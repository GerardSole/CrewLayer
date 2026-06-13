import { getClient } from './client'
import type { Action, ActionListResponse, ActionStats } from '@/types/api'

export async function listActions(
  agentId: string,
  params?: { status?: string; tool_name?: string; limit?: number; cursor?: string },
): Promise<ActionListResponse> {
  const { data } = await getClient().get<ActionListResponse>(
    `/v1/agents/${agentId}/actions`,
    { params },
  )
  return data
}

export async function getAction(agentId: string, actionId: string): Promise<Action> {
  const { data } = await getClient().get<Action>(
    `/v1/agents/${agentId}/actions/${actionId}`,
  )
  return data
}

export async function getActionStats(agentId: string): Promise<ActionStats> {
  const { data } = await getClient().get<ActionStats>(
    `/v1/agents/${agentId}/actions/stats`,
  )
  return data
}
