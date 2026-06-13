import { getClient } from './client'
import type { PromptVersion, PromptDiffResponse } from '@/types/api'

export async function listPromptVersions(
  agentId: string,
): Promise<{ items: PromptVersion[]; count: number }> {
  const { data } = await getClient().get<{ items: PromptVersion[]; count: number }>(
    `/v1/agents/${agentId}/prompts`,
  )
  return data
}

export async function getActivePrompt(agentId: string): Promise<PromptVersion> {
  const { data } = await getClient().get<PromptVersion>(
    `/v1/agents/${agentId}/prompts/active`,
  )
  return data
}

export async function createPromptVersion(
  agentId: string,
  body: { content: string; description?: string },
): Promise<PromptVersion> {
  const { data } = await getClient().post<PromptVersion>(
    `/v1/agents/${agentId}/prompts`,
    body,
  )
  return data
}

export async function activatePromptVersion(
  agentId: string,
  versionId: string,
): Promise<PromptVersion> {
  const { data } = await getClient().post<PromptVersion>(
    `/v1/agents/${agentId}/prompts/${versionId}/activate`,
  )
  return data
}

export async function rollbackPrompt(agentId: string): Promise<PromptVersion> {
  const { data } = await getClient().post<PromptVersion>(
    `/v1/agents/${agentId}/prompts/rollback`,
  )
  return data
}

export async function diffPromptVersions(
  agentId: string,
  a: string,
  b: string,
): Promise<PromptDiffResponse> {
  const { data } = await getClient().get<PromptDiffResponse>(
    `/v1/agents/${agentId}/prompts/diff`,
    { params: { a, b } },
  )
  return data
}
