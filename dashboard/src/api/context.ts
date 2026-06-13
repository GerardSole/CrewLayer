import { getClient } from './client'
import type {
  ContextEntry,
  ContextNamespaceResponse,
  ContextHistoryResponse,
  RollbackResponse,
} from '@/types/api'

export async function listNamespaceKeys(namespace: string): Promise<ContextNamespaceResponse> {
  const { data } = await getClient().get<ContextNamespaceResponse>(`/v1/context/${namespace}`)
  return data
}

export async function readContext(namespace: string, key: string): Promise<ContextEntry> {
  const { data } = await getClient().get<ContextEntry>(`/v1/context/${namespace}/${key}`)
  return data
}

export async function writeContext(
  namespace: string,
  key: string,
  value: Record<string, unknown>,
  options?: { written_by?: string; expected_version?: number },
): Promise<ContextEntry> {
  const { data } = await getClient().put<ContextEntry>(`/v1/context/${namespace}/${key}`, {
    value,
    ...options,
  })
  return data
}

export async function deleteContext(namespace: string, key: string): Promise<void> {
  await getClient().delete(`/v1/context/${namespace}/${key}`)
}

export async function getContextHistory(
  namespace: string,
  key: string,
  limit = 20,
  cursor?: string,
): Promise<ContextHistoryResponse> {
  const { data } = await getClient().get<ContextHistoryResponse>(
    `/v1/context/${namespace}/${key}/history`,
    { params: { limit, cursor } },
  )
  return data
}

export async function rollbackContext(
  namespace: string,
  key: string,
  targetVersion: number,
): Promise<RollbackResponse> {
  const { data } = await getClient().post<RollbackResponse>(
    `/v1/context/${namespace}/${key}/rollback`,
    { target_version: targetVersion },
  )
  return data
}
