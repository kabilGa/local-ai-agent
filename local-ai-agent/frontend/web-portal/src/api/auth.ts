import type { AuthSession } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockLogin } from './devMocks'

export async function login(
  email: string,
  password: string,
): Promise<AuthSession> {
  return tryApiOrMock(
    () => apiRequest<AuthSession>('/auth/login', { method: 'POST', body: { email, password }, auth: false }),
    () => mockLogin(email, password),
  )
}
