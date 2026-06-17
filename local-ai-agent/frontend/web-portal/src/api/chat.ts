import type { ChatRequest, ChatResponse } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockChat } from './devMocks'

export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  return tryApiOrMock(
    () => apiRequest<ChatResponse>('/chat', { method: 'POST', body: request }),
    () => mockChat(request),
  )
}

export async function* streamChatMessage(
  request: ChatRequest,
): AsyncGenerator<string, ChatResponse, undefined> {
  const full = await sendChatMessage(request)
  const text = full.response

  // Character-level chunks for smooth token-by-token streaming UI
  for (const char of text) {
    yield char
    await new Promise((r) => setTimeout(r, 8))
  }

  return full
}
