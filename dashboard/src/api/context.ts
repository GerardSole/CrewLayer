import { getClient } from './client'
import type { ContextEntry, ContextNamespaceResponse } from '@/types/api'

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
  value: unknown,
  options?: { ttl_seconds?: number },
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
