import { getClient } from './client'
import type { PromptVersion } from '@/types/api'

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
