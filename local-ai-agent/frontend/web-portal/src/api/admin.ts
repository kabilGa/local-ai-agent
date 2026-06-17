import type { AdminSettings, AdminUser } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockGetAdminSettings, mockGetAdminUsers } from './devMocks'

export async function getAdminUsers(): Promise<AdminUser[]> {
  return tryApiOrMock(
    () => apiRequest<AdminUser[]>('/admin/users'),
    () => mockGetAdminUsers(),
  )
}

export async function getAdminSettings(): Promise<AdminSettings> {
  return tryApiOrMock(
    () => apiRequest<AdminSettings>('/admin/settings'),
    () => mockGetAdminSettings(),
  )
}
