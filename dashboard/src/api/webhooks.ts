import { getClient } from './client'
import type { WebhookEndpoint, WebhookList } from '@/types/api'

export async function listWebhooks(): Promise<WebhookList> {
  const { data } = await getClient().get<WebhookList>('/v1/webhooks')
  return data
}

export async function createWebhook(body: {
  url: string
  events: string[]
  secret?: string
}): Promise<WebhookEndpoint> {
  const { data } = await getClient().post<WebhookEndpoint>('/v1/webhooks', body)
  return data
}

export async function deleteWebhook(webhookId: string): Promise<void> {
  await getClient().delete(`/v1/webhooks/${webhookId}`)
}

export async function testWebhook(webhookId: string): Promise<{ status: string }> {
  const { data } = await getClient().post<{ status: string }>(
    `/v1/webhooks/${webhookId}/test`,
  )
  return data
}
