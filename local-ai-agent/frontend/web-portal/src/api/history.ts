import type { ConversationDetail, ConversationSummary } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockGetConversation, mockGetConversations } from './devMocks'

export async function getConversations(): Promise<ConversationSummary[]> {
  return tryApiOrMock(
    () => apiRequest<ConversationSummary[]>('/conversations'),
    () => mockGetConversations(),
  )
}

export async function getConversation(
  id: string,
): Promise<ConversationDetail | null> {
  return tryApiOrMock(
    () => apiRequest<ConversationDetail>(`/conversations/${id}`),
    () => mockGetConversation(id),
  )
}
