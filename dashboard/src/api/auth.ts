import axios from 'axios'
import { STORAGE_KEYS, DEFAULT_BASE_URL } from '@/lib/constants'
import type { ApiKey } from '@/types/api'

export async function validateApiKey(baseURL: string, apiKey: string): Promise<boolean> {
  try {
    await axios.get<{ items: ApiKey[] }>(`${baseURL}/v1/api-keys`, {
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
