import { getClient } from './client'
import type { UsageResponse } from '@/types/api'

export async function getUsage(): Promise<UsageResponse> {
  const { data } = await getClient().get<UsageResponse>('/v1/usage')
  return data
}
