import { getClient } from './client'
import type { EvaluationSummary, AnomalyListResponse } from '@/types/api'

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
