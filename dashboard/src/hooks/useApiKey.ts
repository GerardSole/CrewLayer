import { STORAGE_KEYS, DEFAULT_BASE_URL } from '@/lib/constants'

export interface StoredCredentials {
  apiKey: string
  baseURL: string
}

export function getStoredCredentials(): StoredCredentials | null {
  const apiKey = localStorage.getItem(STORAGE_KEYS.API_KEY)
  if (!apiKey) return null
  const baseURL = localStorage.getItem(STORAGE_KEYS.BASE_URL) ?? DEFAULT_BASE_URL
  return { apiKey, baseURL }
}

export function useApiKey(): StoredCredentials | null {
  return getStoredCredentials()
}
