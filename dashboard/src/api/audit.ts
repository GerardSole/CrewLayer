import { getClient } from './client'
import type { AuditLogResponse } from '@/types/api'

export async function listAuditLog(params?: {
  resource_type?: string
  from?: string
  to?: string
  limit?: number
  cursor?: string
}): Promise<AuditLogResponse> {
  const { data } = await getClient().get<AuditLogResponse>('/v1/audit-log', { params })
  return data
}
