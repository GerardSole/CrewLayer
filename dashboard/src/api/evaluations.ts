import { getClient } from './client'
import type { Evaluation, EvaluationSummary, AnomalyListResponse } from '@/types/api'

export async function getEvaluationSummary(agentId: string): Promise<EvaluationSummary> {
  const { data } = await getClient().get<EvaluationSummary>(
    `/v1/agents/${agentId}/evaluations/summary`,
  )
  return data
}

export async function listAnomalies(
  agentId: string,
  resolved?: boolean,
): Promise<AnomalyListResponse> {
  const { data } = await getClient().get<AnomalyListResponse>(
    `/v1/agents/${agentId}/anomalies`,
    { params: resolved !== undefined ? { resolved } : undefined },
  )
  return data
}

export async function submitEvaluation(
  agentId: string,
  actionId: string,
  body: {
    rating_thumbs?: 'up' | 'down'
    rating_score?: number
    notes?: string
    prompt_version_id?: string
  },
): Promise<Evaluation> {
  const { data } = await getClient().post<Evaluation>(
    `/v1/agents/${agentId}/actions/${actionId}/evaluate`,
    body,
  )
  return data
}
