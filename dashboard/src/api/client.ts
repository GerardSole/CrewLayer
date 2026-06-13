import axios, { type AxiosInstance } from 'axios'
import { STORAGE_KEYS, DEFAULT_BASE_URL } from '@/lib/constants'

function createClient(): AxiosInstance {
  const baseURL = localStorage.getItem(STORAGE_KEYS.BASE_URL) ?? DEFAULT_BASE_URL
  const apiKey = localStorage.getItem(STORAGE_KEYS.API_KEY) ?? ''

  const instance = axios.create({
    baseURL,
    headers: {
      'X-API-Key': apiKey,
      'Content-Type': 'application/json',
    },
    timeout: 15_000,
  })

  instance.interceptors.response.use(
    (res) => res,
    (err) => {
      if (err.response?.status === 401) {
        localStorage.removeItem(STORAGE_KEYS.API_KEY)
        localStorage.removeItem(STORAGE_KEYS.BASE_URL)
        window.location.href = '/login'
      }
      return Promise.reject(err)
    },
  )

  return instance
}

export function getClient(): AxiosInstance {
  return createClient()
}
