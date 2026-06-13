import { getClient } from './client'
import type { Action, ActionListResponse, ActionStatsResponse, Replay, ReplayListResponse } from '@/types/api'

export async function listActions(
  agentId: string,
  params?: {
    status?: string
    tool?: string
    since?: string
    until?: string
    limit?: number
    cursor?: string
  },
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

export async function getActionStats(agentId: string): Promise<ActionStatsResponse> {
  const { data } = await getClient().get<ActionStatsResponse>(
    `/v1/agents/${agentId}/actions/stats`,
  )
  return data
}

export async function createReplay(
  agentId: string,
  fromTimestamp: string,
  toTimestamp: string,
  speed: number,
): Promise<Replay> {
  const { data } = await getClient().post<Replay>(`/v1/agents/${agentId}/replays`, {
    from_timestamp: fromTimestamp,
    to_timestamp: toTimestamp,
    speed,
  })
  return data
}

export async function getReplay(agentId: string, replayId: string): Promise<Replay> {
  const { data } = await getClient().get<Replay>(
    `/v1/agents/${agentId}/replays/${replayId}`,
  )
  return data
}

export async function listReplays(agentId: string): Promise<ReplayListResponse> {
  const { data } = await getClient().get<ReplayListResponse>(
    `/v1/agents/${agentId}/replays`,
  )
  return data
}
