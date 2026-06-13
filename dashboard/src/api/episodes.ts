import { getClient } from './client'
import type { Episode, EpisodeDetail } from '@/types/api'

export async function listEpisodes(
  agentId: string,
  status?: 'open' | 'completed',
): Promise<Episode[]> {
  const { data } = await getClient().get<Episode[]>(`/v1/agents/${agentId}/episodes`, {
    params: status ? { status } : undefined,
  })
  return data
}

export async function getEpisodeDetail(
  agentId: string,
  episodeId: string,
): Promise<EpisodeDetail> {
  const { data } = await getClient().get<EpisodeDetail>(
    `/v1/agents/${agentId}/episodes/${episodeId}`,
  )
  return data
}
