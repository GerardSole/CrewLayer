import axios from 'axios'
import { STORAGE_KEYS, DEFAULT_BASE_URL } from '@/lib/constants'
import { getClient } from './client'
import type { ApiKey, ApiKeyCreated } from '@/types/api'

export async function validateApiKey(baseURL: string, apiKey: string): Promise<boolean> {
  try {
    await axios.get<ApiKey[]>(`${baseURL}/v1/api-keys`, {
      headers: { 'X-API-Key': apiKey },
      timeout: 10_000,
    })
    return true
  } catch {
    return false
  }
}

export function storeCredentials(baseURL: string, apiKey: string): void {
  localStorage.setItem(STORAGE_KEYS.BASE_URL, baseURL.replace(/\/$/, ''))
  localStorage.setItem(STORAGE_KEYS.API_KEY, apiKey)
}

export function clearCredentials(): void {
  localStorage.removeItem(STORAGE_KEYS.API_KEY)
  localStorage.removeItem(STORAGE_KEYS.BASE_URL)
}

export function getBaseURL(): string {
  return localStorage.getItem(STORAGE_KEYS.BASE_URL) ?? DEFAULT_BASE_URL
}

export async function listApiKeys(): Promise<ApiKey[]> {
  const { data } = await getClient().get<ApiKey[]>('/v1/api-keys')
  return data
}

export async function createApiKey(body: {
  name: string
  scopes: string[]
  agent_ids: string[]
  expires_at?: string
}): Promise<ApiKeyCreated> {
  const { data } = await getClient().post<ApiKeyCreated>('/v1/api-keys', body)
  return data
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await getClient().delete(`/v1/api-keys/${keyId}`)
}
