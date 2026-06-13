import { getClient } from './client'
import type { Session, SessionList } from '@/types/api'

export async function listSessions(params?: {
  agent_id?: string
  limit?: number
}): Promise<SessionList> {
  const { data } = await getClient().get<SessionList>('/v1/sessions', { params })
  return data
}

export async function closeSession(sessionId: string): Promise<Session> {
  const { data } = await getClient().post<Session>(`/v1/sessions/${sessionId}/close`)
  return data
}
