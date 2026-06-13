import { getClient } from './client'
import type { SessionList } from '@/types/api'

export async function listSessions(params?: {
  agent_id?: string
  limit?: number
}): Promise<SessionList> {
  const { data } = await getClient().get<SessionList>('/v1/sessions', { params })
  return data
}
