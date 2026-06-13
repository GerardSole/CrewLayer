import { getClient } from './client'
import type {
  Evaluation,
  EvaluationSummary,
  AnomalyListResponse,
  Anomaly,
  ABTest,
  ABTestListResponse,
  ABTestResults,
  ABTestWinner,
} from '@/types/api'

export async function getEvaluationSummary(agentId: string): Promise<EvaluationSummary> {
  const { data } = await getClient().get<EvaluationSummary>(
    `/v1/agents/${agentId}/evaluations/summary`,
  )
  return data
}

export async function listEvaluations(
  agentId: string,
  params?: { from_date?: string; to_date?: string; prompt_version_id?: string; limit?: number; offset?: number },
): Promise<{ items: Evaluation[]; count: number }> {
  const { data } = await getClient().get<{ items: Evaluation[]; count: number }>(
    `/v1/agents/${agentId}/evaluations`,
    { params },
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

export async function resolveAnomaly(agentId: string, anomalyId: string): Promise<Anomaly> {
  const { data } = await getClient().post<Anomaly>(
    `/v1/agents/${agentId}/anomalies/${anomalyId}/resolve`,
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

export async function listABTests(agentId: string): Promise<ABTestListResponse> {
  const { data } = await getClient().get<ABTestListResponse>(
    `/v1/agents/${agentId}/ab-tests`,
  )
  return data
}

export async function getABTestResults(agentId: string, testId: string): Promise<ABTestResults> {
  const { data } = await getClient().get<ABTestResults>(
    `/v1/agents/${agentId}/ab-tests/${testId}/results`,
  )
  return data
}

export async function createABTest(
  agentId: string,
  body: {
    name: string
    variant_a_prompt_version_id: string
    variant_b_prompt_version_id: string
    traffic_split: number
  },
): Promise<ABTest> {
  const { data } = await getClient().post<ABTest>(
    `/v1/agents/${agentId}/ab-tests`,
    body,
  )
  return data
}

export async function completeABTest(
  agentId: string,
  testId: string,
  winner: ABTestWinner,
): Promise<ABTest> {
  const { data } = await getClient().post<ABTest>(
    `/v1/agents/${agentId}/ab-tests/${testId}/complete`,
    { winner },
  )
  return data
}
